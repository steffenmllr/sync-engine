from hypothesis.utils.conventions import not_set

def accept(f):
    def test_message_body_storage(config, message, sample_input=not_set, encrypt=not_set):
        return f(config=config, message=message, sample_input=sample_input, encrypt=encrypt)
    return test_message_body_storage
