from django import forms


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
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Введите сообщение...'}),
    )
