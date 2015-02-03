from inbox.models.meta import init_models
locals().update({model.__name__: model for model in init_models()})
