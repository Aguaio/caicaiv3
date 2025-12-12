from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_solicitudconfeccion_cotizacion_aceptada_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='producto',
            name='activo',
            field=models.BooleanField(default=True),
        ),
    ]
