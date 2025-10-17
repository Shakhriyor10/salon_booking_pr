from django import forms
from django.conf import settings


IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}


class SupportMessageForm(forms.Form):
    contact_name = forms.CharField(
        label='Ваше имя',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Ваше имя'}),
    )
    contact_email = forms.EmailField(
        label='Электронная почта',
        required=False,
        widget=forms.EmailInput(attrs={'placeholder': 'Электронная почта'}),
    )
    message = forms.CharField(
        label='Сообщение',
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Введите сообщение...'}),
    )
    attachment = forms.ImageField(
        label='Фото',
        required=False,
    )

    def clean(self):
        cleaned_data = super().clean()
        message = cleaned_data.get('message')
        attachment = cleaned_data.get('attachment')

        if not message and not attachment:
            raise forms.ValidationError('Добавьте сообщение или прикрепите изображение.')

        if attachment:
            content_type = getattr(attachment, 'content_type', None)
            if content_type and content_type not in IMAGE_CONTENT_TYPES:
                raise forms.ValidationError('Можно загрузить только изображение (JPEG, PNG, GIF, WEBP).')
            max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 10 * 1024 * 1024)
            if attachment.size > max_size:
                raise forms.ValidationError('Файл слишком большой. Максимальный размер 10 МБ.')

        return cleaned_data
