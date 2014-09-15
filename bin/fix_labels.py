#!/usr/bin/env python
import click
from sqlalchemy.orm import joinedload
from inbox.models.session import session_scope
from inbox.models import Thread
from inbox.models.backends.eas import EASAccount


def folder_names(folders):
    return [f.name for f in folders]


@click.command()
@click.option('--thread_id_file')
@click.option('--dry_run/--no_dry_run', default=False)
def update_thread_labels(thread_id_file, dry_run):
    with open(thread_id_file) as f:
        thread_ids = list(set(int(thread_id) for thread_id in
                              f.read().split(',')))
    with session_scope(ignore_soft_deletes=False) as db_session:
        # Need ignore_soft_deletes=False so we actually delete FolderItem
        # entries.
        threads = db_session.query(Thread).filter(
            Thread.id.in_(thread_ids)).options(joinedload('messages').
                                               joinedload('imapuids').
                                               joinedload('folder'),
                                               joinedload('folderitems').
                                               joinedload('folder'))
        affected_thread_count = 0
        for thread in threads:
            account = thread.namespace.account
            if isinstance(account, EASAccount):
                # skip patching up EAS thread labels for now.
                # Note: verified that no production EAS threads were actually
                # affected. -- emfree
                print "skipping EAS thread {}".format(thread.id)
                continue
            expected_folders = set()
            current_folders = set(thread.folders)
            for message in thread.messages:
                for imapuid in message.imapuids:
                    expected_folders.add(imapuid.folder)
            if expected_folders != current_folders:
                print ("affected thread {}. Should have folders {}, have {}".
                       format(thread.id, folder_names(expected_folders),
                              folder_names(thread.folders)))
                affected_thread_count += 1
                if not dry_run:
                    folders_to_discard = current_folders - expected_folders
                    folders_to_add = expected_folders - current_folders
                    # This also triggers tag updates on the thread.
                    for folder in folders_to_discard:
                        thread.folders.discard(folder)
                    for folder in folders_to_add:
                        thread.folders.add(folder)
        print "affected thread count: {}".format(affected_thread_count)


if __name__ == '__main__':
    update_thread_labels()
