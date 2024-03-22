# Generated by Django 4.2.11 on 2024-03-14 09:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('signal_app', '0002_alter_userprofile_discord_id_alter_userprofile_user'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='userprofile',
            name='user',
        ),
        migrations.AddField(
            model_name='userprofile',
            name='discord_username',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='discord_id',
            field=models.CharField(blank=True, max_length=18, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='subscription_type',
            field=models.CharField(default='FREE', max_length=10),
        ),
    ]
