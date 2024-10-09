import os
from discord.ext import commands
from discord.ui import Button, View, Modal, InputText
from disnake import TextInputStyle
import discord
from discord.commands import SlashCommandGroup
from disnake.ui import TextInput
from django.http import JsonResponse
from django.utils.html import format_html
from django.views.decorators.csrf import csrf_exempt
from .models import UserProfile
import json
from django.conf import settings
import pandas as pd
import numpy as np
import random
import smtplib  # Example for sending email
import ccxt
from django.core.mail import send_mail
import aiohttp
from asgiref.sync import sync_to_async
import asyncio

asyncio.set_event_loop(asyncio.new_event_loop())

# Only use commands.Bot since it can do everything discord.bot can do
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Group for slash commands
trading_signals_group = SlashCommandGroup("trading", "Commands related to trading signals")

MESSAGE_ID = 1285840423268515913

CRYPTO_PAIRS = [
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'ADA/USDT',
    'SOL/USDT', 'XRP/USDT', 'DOT/USDT', 'MATIC/USDT',
    'SNX/USDT', 'FIL/USDT',
    'APT/USDT', 'LTC/USDT', 'UNI/USDT',
    'TRX/USDT', 'APE/USDT', 'XLM/USDT'
]

# Function to calculate the EMA
async def calculate_ema(prices, period):
    return prices.ewm(span=period, adjust=False).mean()

# Function to calculate the RSI
async def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gains = delta.where(delta > 0, 0)
    losses = -delta.where(delta < 0, 0)
    avg_gain = gains.rolling(window=period, min_periods=1).mean()
    avg_loss = losses.rolling(window=period, min_periods=1).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# Function to calculate CCI
async def calculate_cci(df, period=10):
    TP = (df['high'] + df['low'] + df['close']) / 3
    sma = TP.rolling(window=period).mean()
    mean_deviation = TP.rolling(window=period).apply(lambda x: np.fabs(x - x.mean()).mean())
    cci = (TP - sma) / (0.015 * mean_deviation)
    return cci

# Function to calculate ATR
async def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.DataFrame({'HL': high_low, 'HC': high_close, 'LC': low_close}).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

class SignalSelectionView(View):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_item(Button(label="🚨 Get our Exclusive Signals", style=discord.ButtonStyle.blurple, custom_id="vip_signals"))

    
# Function to fetch data and calculate signal
async def generate_signal(pair):
    exchange = ccxt.binanceus()
    symbol = pair
    timeframe = '15m'
    limit = 100  # Fetch last 100 candles
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['EMA25'] = await calculate_ema(df['close'], 25)
    df['RSI4'] = await calculate_rsi(df['close'], 4)
    df['CCI10'] = await calculate_cci(df, 10)
    df['ATR14'] = await calculate_atr(df, 14)
    latest = df.iloc[-1]
    if latest['RSI4'] < 30 and latest['CCI10'] < -100 and latest['close'] < latest['EMA25']:
        tp = latest['close'] - (1.5 * latest['ATR14'])
        tp1 = latest['close'] - (2 * latest['ATR14'])
        sl = latest['close'] + (2 * latest['ATR14'])
        tp_formatted = f"{tp:.4f}"
        tp1_formatted = f"{tp1:.4f}"
        sl_formatted = f"{sl:.4f}"
        return f'🎯 **Pair**: {symbol} \n 🔻 **Action**: Sell at **{latest["close"]}** \n \n 💰 **Take Profit Targets**:\n 	•	TP1: **{tp_formatted}**\n 	•	TP2: **{tp1_formatted}** \n \n ❌ **Stop Loss: {sl_formatted}** \n \n ⚡️ **Leverage**: _Optional_ \n 🔗 _Trade responsibly and follow market trends_ \n ~~                                                                                         ~~\n \n \n '
    elif latest['RSI4'] > 70 and latest['CCI10'] > 100 and latest['close'] > latest['EMA25']:
        tp = latest['close'] + (1.5 * latest['ATR14'])
        tp1 = latest['close'] + (2 * latest['ATR14'])
        sl = latest['close'] - (2 * latest['ATR14'])
        tp_formatted = f"{tp:.4f}"
        tp1_formatted = f"{tp1:.4f}"
        sl_formatted = f"{sl:.4f}"
        return f'🎯 **Pair**: {symbol} \n 💹 **Action**: Buy at **{latest["close"]}** \n \n 💰 **Take Profit Targets**:\n 	•	TP1: **{tp_formatted}**\n 	•	TP2: **{tp1_formatted}** \n \n ❌ **Stop Loss: {sl_formatted}** \n \n ⚡️ **Leverage**: _Optional_ \n 🔗 _Trade responsibly and follow market trends_ \n ~~                                                                                         ~~ \n \n \n'
    return 'HOLD'

async def send_signal(discord_id, signal):
    user = await bot.fetch_user(int(discord_id))
    if user and signal != 'HOLD':
        await user.send(f"🌐 **New Trade Signal Alert** 🌐 \n {signal}")
        
async def register_user_for_signals(discord_user, subscription_type):
    discord_id = str(discord_user.id)
    discord_username = f"{discord_user.name}#{discord_user.discriminator}"

    # await sync_to_async(UserProfile.objects.all().delete, thread_sensitive=True)()
    
    def get_or_create_user_profile():
        user_profile, created = UserProfile.objects.get_or_create(
            discord_id=discord_id,
            defaults={'discord_username': discord_username, 'subscription_type': subscription_type}
        )
        if not created:
            # If the UserProfile already existed, update the subscription type
            user_profile.discord_username = discord_username
            user_profile.subscription_type = subscription_type
            user_profile.save()
        return user_profile

    # Use Django's ORM operations in an async way
    await sync_to_async(get_or_create_user_profile, thread_sensitive=True)()

async def send_or_retrieve_message(channel):
    try:
        # Attempt to fetch the message from the channel using the hardcoded message ID
        message = await channel.fetch_message(MESSAGE_ID)
        print("Message already exists. No need to resend.")
    except discord.NotFound:
        # If the message with the given ID does not exist, send a new one
        view = SignalSelectionView()
        message = await channel.send("Ready to get access to our exclusive trading signals?", view=view)
        # Note: Here, you would ideally update HARDCODED_MESSAGE_ID to the new message's ID for future checks,
        # but this isn't possible with a hardcoded approach without manually updating and restarting the bot.
        print("New message sent.")
    except discord.HTTPException as e:
        # Handle other potential HTTP exceptions
        print(f"Failed to retrieve or send the message due to an HTTPException: {e}")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    # Check if the message with buttons has already been sent to avoid duplication
    # This is simplified; implement based on your requirement
    channel = bot.get_channel(1280258256782102640)  # Adjust with your target channel ID
    # Ensure this message is only sent once or based on some condition
    await send_or_retrieve_message(channel)
    # Start the periodic signal check task
    bot.loop.create_task(periodic_signal_check())

# Create a dictionary to store generated codes for emails
async def send_verification_code(email):
    # Generate a random 6-digit verification code
    verification_code = str(random.randint(100000, 999999))
    
    try:
        print("About Sending Verification Mail")
        
        # Subject for the email
        subject = f'Your Signal Access Verification Code is {verification_code}'
        
        # HTML formatted email content
        message = format_html(
            f'<strong>Signal Access Verification Code</strong>,<br><br>'
            f'We’ve received your request to access exclusive trading signals. '
            f'To complete the process, please use the following verification code:<br><br>'
            f'<strong style="font-size: 2em;">🛡️ {verification_code} 🛡️</strong><br><br>'
            f'Please enter this code in the provided field to unlock your access.<br>'
            f'<em>Note: For your security, do not share this code with anyone.</em><br><br>'
            f'If you did not request access to signals, you can safely ignore this email.<br><br>'
            f'Trade safely,<br>'
            f'The Market Experts Team'
        )
        
        from_email = settings.DEFAULT_FROM_EMAIL
        to_email = [email]

        # Send the email using the html_message parameter for HTML content
        send_mail(subject, '', from_email, to_email, html_message=message)

        print(f"Verification code {verification_code} sent to {email}")

        # Return the verification code directly
        return verification_code, 200

    except Exception as e:
        print(f"Failed to send email: {e}")
        return {"message": "Failed to send code", "code": None}, 500

# Async function to verify the code
async def verify_code(input, email, code):
    print(f"Verifing code and User says {input} code is {code}")
    # Check if the entered code matches the stored one
    if int(input) == int(code):
        print(f"Code {code} is correct for {email}")
        return 200
    else:
        print(f"Invalid code {code} for {email}")
        return 404
    
# Modal class to collect the user's email
# Modal class to collect the user's email and verify the code
class CodeModal(Modal):
    def __init__(self, email, code, *args, **kwargs):
        super().__init__(title="Enter 6-Digit Verification Code", *args, **kwargs)
        
        # Store the passed email and code
        self.email = email  # Passed in from the previous modal
        self.code = code  # Verification code to match
        
        # InputText for the user to enter the code
        self.verification_code = InputText(
            label="Verification Code", 
            custom_id="code", 
            style=TextInputStyle.short, 
            placeholder="123456", 
            required=True, 
            max_length=6  # Ensure it is a 4-digit code
        )
        # Add InputText to the modal
        self.add_item(self.verification_code)

    # Callback method when the modal is submitted
    async def callback(self, interaction: discord.Interaction):
        # Get the entered code from the user
        input_code = self.verification_code.value

        _code = int(self.code)

        print(f"Code entered by user: {input_code}")
        print(f"Actual code to match: {_code}")
        
        # Check if the entered code matches the one that was sent
        if int(input_code) == int(_code):
            # If it matches, notify the user of successful verification
            await interaction.response.send_message("Code verified successfully.", ephemeral=True)  # Ephemeral ensures only the user sees this message
            await register_user_for_signals(interaction.user, 'VIP')
        else:
            # If it doesn't match, notify the user of invalid code
            await interaction.response.send_message("Invalid code. Please try again.", ephemeral=True)


# Modal class to collect the user's email
class EmailModal(Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(title="Enter Your Email for Exclusive Signals", *args, **kwargs)
        self.email = InputText(label="Email Address", custom_id="user_email", style=TextInputStyle.short, placeholder="you@example.com", required=True)
        self.add_item(self.email)

    async def callback(self, interaction: discord.Interaction):
        email = self.email.value
        print(f"Email received: {email}")

        # Defer the interaction response to allow background processing
        await interaction.response.defer(ephemeral=True)

        # Send the verification code via email in the background
        code, status = await send_verification_code(email)

        # Store the email and code in pending_users for later verification
        pending_users[interaction.user.id] = {
            'state': 'awaiting_code',
            'email': email,
            'code': code
        }
        print("Pending Users Set")

        if status == 200:
            print("Code has been sent, prompting user to enter it...")
            # Create a button to trigger the second modal
            button = Button(label="Enter Verification Code", style=discord.ButtonStyle.success)

            async def button_callback(interaction):
                await interaction.response.send_modal(CodeModal(email, code))

            button.callback = button_callback

            view = View()
            view.add_item(button)

            # Send a follow-up message after sending the email
            await interaction.followup.send("Verification code has been sent to your email. Click the button below to enter the code.", view=view, ephemeral=True)
        else:
            await interaction.followup.send("Failed to send verification code. Please try again.", ephemeral=True)


# Function to confirm the code
async def confirming_code(email, code):
    print(f"Verifying code for {email}...")
    response_json, status = await verify_code(email, code)
    
    if status == 200:
        return {"message": "Code verified successfully."}, 200
    elif status == 404:
        return {"message": "Invalid code. Please try again."}, 404
    else:
        return {"message": "An unexpected error occurred. Please try again later."}, 500

@bot.event
async def on_interaction(interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data['custom_id']
        discord_id = str(interaction.user.id)

        # Fetch or create a user profile
        user_profile, created = await sync_to_async(UserProfile.objects.get_or_create, thread_sensitive=True)(
            discord_id=discord_id
        )

        # Determine the intended subscription type from the interaction
        if custom_id == "free_signals":
            if user_profile.subscription_type == 'FREE':
                follow_up_message = "You already have been registered for Free Signals!"

                if user_profile.received_signals_count >= 2:
                    follow_up_message = "You have exhausted your lifetime free signals. Upgrade to 👑VIP for more exclusive signals."
            else :
                user_profile.subscription_type == 'FREE'
                # Increment the count and update the user profile
                await sync_to_async(user_profile.save, thread_sensitive=True)()
                await register_user_for_signals(interaction.user, 'FREE')
                follow_up_message = "Congratulations you've just been registered for Free Signals!"

        elif custom_id == "vip_signals":
            if user_profile.subscription_type != 'VIP':
                # If not VIP, prompt for email
                await interaction.response.send_modal(EmailModal())
                return  # Exit to avoid sending follow-up message prematurely
            else:
                follow_up_message = "👑 You have already been registered for our Exclusive Signals!"
                
        # Send a follow-up message after processing
        try:
            # If this is the initial response to the interaction
            await interaction.response.send_message(follow_up_message, ephemeral=True)
        except discord.NotFound as e:
            # If the interaction is no longer valid
            print(f"Interaction is no longer valid: {e}")
        except discord.errors.InteractionResponded as e:
            # If we've already responded to the interaction, use followup
            await interaction.followup.send(follow_up_message, ephemeral=True)
        except Exception as e:
            # Catch any other exceptions that might occur
            print(f"An unexpected error occurred: {e}")

@csrf_exempt
async def tradingview_signal(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        discord_id = data.get('discord_id')
        # Generate signal based on latest market data
        signal = await generate_signal(pair)

        # Fetch or create the user profile
        user_profile, _ = await sync_to_async(UserProfile.objects.get_or_create, thread_sensitive=True)(discord_id=discord_id)
        
        # Check subscription type and send signal if conditions are met
        if (user_profile.subscription_type == 'FREE' and user_profile.received_signals_count < 2) or user_profile.subscription_type == 'VIP':
            await send_signal(discord_id, signal)
            user_profile.received_signals_count += 1
            await sync_to_async(user_profile.save, thread_sensitive=True)()

        return JsonResponse({'status': 'OK', 'signal': signal})
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)

async def generate_and_send_signals_for_pair(pair):
    # Generate signals for a specific pair
    # This is a placeholder, replace with your actual signal generation logic
    signal = await generate_signal(pair)
    return signal

async def periodic_signal_check():
    while True:
        user_profiles = await sync_to_async(list)(UserProfile.objects.all())
        
        for pair in CRYPTO_PAIRS:
            signal = await generate_signal(pair)
            
            # Skip if no signal is generated for this pair
            if not signal or signal == 'HOLD':
                continue

            # Process VIP users for all pairs
            vip_profiles = [profile for profile in user_profiles if profile.subscription_type == 'VIP']
            for profile in vip_profiles:
                await send_signal(profile.discord_id, signal)
            
            # Special handling for FREE users - only send BTC/USDT signals and check limit
            if pair == 'BTC/USDT':
                free_profiles = [profile for profile in user_profiles if profile.subscription_type == 'FREE']
                for profile in free_profiles:
                    if profile.received_signals_count < 2:
                        await send_signal(profile.discord_id, signal)
                        profile.received_signals_count += 1
                        await sync_to_async(profile.save, thread_sensitive=True)()
                        # Notify to upgrade after reaching the limit
                        if profile.received_signals_count >= 2:
                            await notify_to_upgrade(profile.discord_id)
        
        # Wait before starting the next round of checks
        await asyncio.sleep(1000)

async def notify_to_upgrade(discord_id):
    user = await bot.fetch_user(int(discord_id))
    await user.send("You have exhausted your lifetime free signals, Kindly Upgrade to get unlimited Exclusive singals accross 20 diffrent pairs")

pending_emails = {}  # Dictionary to keep track of users who need to input their email
pending_users = {}

# Event handler for message
import re

@bot.event
async def on_message(message):
    # Ignore messages from the bot itself or messages from servers (public channels)
    if message.author == bot.user or message.guild is not None:
        return
    
    user = message.author

    user_id = message.author.id

    # If the user is sending a DM
    if isinstance(message.channel, discord.DMChannel):

        # Handle email input (initial state)
        if user_id in pending_users and pending_users[user_id] == 'awaiting_email':
            email = message.content.strip()

            # Validate email format (simple validation with @ symbol)
            if "@" in email and re.match(r"[^@]+@[^@]+\.[^@]+", email):
                code, status = await send_verification_code(email)

                if status == 200:
                    await message.channel.send("A verification code has been sent to your email. Please reply with the code you received.")
                    # Store the email and code in pending_users for later verification
                    pending_users[user_id] = {
                        'state': 'awaiting_code',
                        'email': email,
                        'code': code
                    }
                else:
                    await message.channel.send("Failed to send the verification code. Please try again.")
            else:
                await message.channel.send("Invalid email format. Please provide a valid email.")

        # Handle code verification
        elif user_id in pending_users and pending_users[user_id]['state'] == 'awaiting_code':
            input_code = message.content.strip()

            if input_code:
                print("Trying to verify the code")
                # Retrieve stored email and code
                email = pending_users[user_id]['email']
                code = pending_users[user_id]['code']

                _code = int(list(code)[0])
                print(f"Code sent to user is {_code}")
                print(f"User Input Code is {input_code}")
                status = await verify_code(input_code, email, _code)

                if status == 200:
                    await message.channel.send("Code verified successfully! You're now registered for Exclusive signals.")
                    await register_user_for_signals(user, 'VIP')
                    del pending_users[user_id]  # Cleanup after handling
                else:
                    await message.channel.send("Incorrect Code! Kindly input the correct code sent to your email.")
                    del pending_users[user_id]  # Cleanup after handling
            else:
                await message.channel.send("No Code Detected. Please start again by providing your email.")
                pending_users[user_id] = 'awaiting_email'

        # Handle initial greeting and start email collection
        elif 'hello' in message.content.lower() and user_id not in pending_users:
            
            pending_users[user_id] = 'awaiting_email'
            await message.channel.send("Welcome! Please reply with your email to start using Exclusive signals.")

        else:
            await message.channel.send("Please provide a valid email to get started.")


token = os.getenv('DISCORD_BOT_TOKEN')
bot.run(token)