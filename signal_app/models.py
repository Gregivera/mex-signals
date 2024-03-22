from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    discord_id = models.CharField(max_length=18, unique=True, null=True, blank=True)  # Discord IDs are 18 characters long
    discord_username = models.CharField(max_length=255, null=True, blank=True)  # Adjust length as needed
    subscription_type = models.CharField(max_length=10, default='FREE')  # Example field for subscription type
    received_signals_count = models.IntegerField(default=0)  # Example field for tracking received signals

    def __str__(self):
        return self.discord_username