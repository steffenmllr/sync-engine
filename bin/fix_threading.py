#!/usr/bin/env python
import click
from inbox.models.session import session_scope
from inbox.models import Message, Account, Part, Block
from inbox.models.backends.imap import ImapThread


@click.command()
@click.option('--dry_run/--no_dry_run', default=False)
def fix_threads(dry_run):
    with session_scope() as db_session:
        generic_accounts = db_session.query(Account). \
            filter(Account.discriminator.in_(('genericaccount',
                                              'outlookccount')))
        for account in generic_accounts:
            ns_id = account.namespace.id
            print "handling namespace_id {}".format(ns_id)
            q = db_session.query(Message).join(Part).join(Block).filter(
                Block.namespace_id == ns_id)
            affected_count = 0
            for message in q:
                if (message.parts and message.parts[0].block.namespace_id !=
                        message.thread.namespace_id):
                    correct_namespace = message.parts[0].block.namespace
                    assert correct_namespace.id == ns_id
                    affected_count += 1
                    print ("mismatched message {} on thread {}".
                           format(message.id, message.thread.id))
                    #if not dry_run:
                    #    new_thread = ImapThread.from_imap_message(
                    #        db_session, namespace=correct_namespace,
                    #        message=message)
                    #    db_session.add(new_thread)
                    #    db_session.flush()
                    #    message.thread = new_thread
                    #    print ("created new thread {} for message {} "
                    #           "on namespace {}".format(new_thread.id,
                    #                                    message.id,
                    #                                    correct_namespace.id))

            print "{} mismatched messages found for namespace {}".format(
                affected_count, ns_id)
        #db_session.commit()

if __name__ == '__main__':
    fix_threads()
