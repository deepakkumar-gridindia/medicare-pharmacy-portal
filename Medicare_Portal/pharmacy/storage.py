from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class ProjectRootStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.PROJECT_ROOT)
