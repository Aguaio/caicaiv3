from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_solicitudconfeccion'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitudconfeccion',
            name='observaciones_admin',
            field=models.TextField(blank=True, default='', null=True),
        ),
    ]
