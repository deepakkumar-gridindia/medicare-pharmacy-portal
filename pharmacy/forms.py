from django import forms

from pharmacy.models import CallSession


class ExcelUploadForm(forms.Form):
    excel_file = forms.FileField()


class StartCallForm(forms.Form):
    channel = forms.ChoiceField(choices=CallSession.CHANNEL_CHOICES)


class CallMessageForm(forms.Form):
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
