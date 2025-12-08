from django import forms
from django.contrib.auth import get_user_model
from .models import SolicitudConfeccion

User = get_user_model()


class RegistroClienteForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Ingresa una contraseña segura",
                "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-300",
            }
        ),
    )
    password2 = forms.CharField(
        label="Confirmar contraseña",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Vuelve a escribir la contraseña",
                "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-300",
            }
        ),
    )

    class Meta:
        model = User
        fields = ["username", "email", "direccion", "telefono"]
        labels = {
            "username": "Nombre de usuario",
            "email": "Correo electrónico",
            "direccion": "Dirección",
            "telefono": "Teléfono",
        }
        widgets = {
            "username": forms.TextInput(
                attrs={
                    "placeholder": "Ej: yordan123",
                    "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-300",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "placeholder": "tucorreo@ejemplo.com",
                    "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-300",
                }
            ),
            "direccion": forms.TextInput(
                attrs={
                    "placeholder": "Calle, número, ciudad",
                    "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-300",
                }
            ),
            "telefono": forms.TextInput(
                attrs={
                    "placeholder": "+56 9 XXXX XXXX",
                    "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-300",
                }
            ),
        }

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Ese nombre de usuario ya existe.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Ese correo ya está registrado.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password1")
        p2 = cleaned_data.get("password2")

        if p1 and p2 and p1 != p2:

            raise forms.ValidationError("Las contraseñas no coinciden.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        # Usamos password1 como contraseña final
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user

class SolicitudConfeccionForm(forms.ModelForm):
    class Meta:
        model = SolicitudConfeccion
        fields = ["nombre", "correo", "telefono", "tipo_prenda", "descripcion_diseno"]
        labels = {
            "nombre": "Nombre completo",
            "correo": "Correo electrónico",
            "telefono": "Teléfono",
            "tipo_prenda": "Tipo de prenda",
            "descripcion_diseno": "Descripción del diseño",
        }
        widgets = {
            "nombre": forms.TextInput(attrs={"placeholder": "Tu nombre completo"}),
            "correo": forms.EmailInput(attrs={"placeholder": "tucorreo@ejemplo.com"}),
            "telefono": forms.TextInput(attrs={"placeholder": "+56 9 XXXX XXXX"}),
            "tipo_prenda": forms.Select(),
            "descripcion_diseno": forms.Textarea(
                attrs={"rows": 4, "placeholder": "Describe tu diseño, materiales, colores, etc."}
            ),
        }