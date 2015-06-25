from hypothesis.utils.conventions import not_set

def accept(f):
    def test_encoded_format(config, sample_input=not_set, encrypt=not_set):
        return f(config=config, sample_input=sample_input, encrypt=encrypt)
    return test_encoded_format
