import os
import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, InputText
from disnake import TextInputStyle
from discord.commands import SlashCommandGroup
from disnake.ui import TextInput
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import UserProfile
import json
import pandas as pd
import numpy as np
import ccxt
import aiohttp
from asgiref.sync import sync_to_async
import asyncio

# Only use commands.Bot since it can do everything discord.bot can do
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Group for slash commands
trading_signals_group = SlashCommandGroup("trading", "Commands related to trading signals")

MESSAGE_ID = 1219183295925981265

CRYPTO_PAIRS = [
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'ADA/USDT',
    'SOL/USDT', 'XRP/USDT', 'DOT/USDT', 'MATIC/USDT',
    'SNX/USDT', 'XMR/USDT', 'FIL/USDT',
    'APT/USDT', 'QNT/USDT', 'LTC/USDT', 'UNI/USDT',
    'TIA/USDT', 'TRX/USDT', 'APE/USDT', 'XLM/USDT'
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
        self.add_item(Button(label="Get Started for Free", style=discord.ButtonStyle.green, custom_id="free_signals"))
        self.add_item(Button(label="👑VIP Signals", style=discord.ButtonStyle.blurple, custom_id="vip_signals"))

    
# Function to fetch data and calculate signal
async def generate_signal(pair):
    exchange = ccxt.binance()
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
        tp = latest['close'] - (2 * latest['ATR14'])
        sl = latest['close'] + (2 * latest['ATR14'])
        tp_formatted = f"{tp:.2f}"
        sl_formatted = f"{sl:.2f}"
        return f'↘️ Sell {symbol} at {latest["close"]} \n 🟢 Take profit @{tp_formatted} \n 🔴 Stop loss@{sl_formatted}'
    elif latest['RSI4'] > 70 and latest['CCI10'] > 100 and latest['close'] > latest['EMA25']:
        tp = latest['close'] + (2 * latest['ATR14'])
        sl = latest['close'] - (2 * latest['ATR14'])
        tp_formatted = f"{tp:.2f}"
        sl_formatted = f"{sl:.2f}"
        return f'↗️ Buy {symbol} at {latest["close"]} \n 🟢 Take profit @{tp_formatted} \n 🔴 Stop loss@{sl_formatted}'
    return 'HOLD'

async def send_signal(discord_id, signal):
    user = await bot.fetch_user(int(discord_id))
    if user and signal != 'HOLD':
        await user.send(f"🚦New trading signal: {signal}")
        
async def register_user_for_signals(discord_user, subscription_type):
    discord_id = str(discord_user.id)
    discord_username = f"{discord_user.name}#{discord_user.discriminator}"
    
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
    channel = bot.get_channel(1205252965439512596)  # Adjust with your target channel ID
    # Ensure this message is only sent once or based on some condition
    await send_or_retrieve_message(channel)
    # Start the periodic signal check task
    bot.loop.create_task(periodic_signal_check())
    
class EmailModal(Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(title="Enter Your Email for VIP Signals", *args, **kwargs)
        self.email = InputText(label="Email Address", custom_id="user_email" ,style=TextInputStyle.short, placeholder="you@example.com", required=True)
        self.add_item(self.email)

    async def callback(self, interaction: discord.Interaction):
        email = self.email.value
        print(f"Discord Interaction {discord.Interaction}")
        response_json, status = await check_email_for_vip(email)

        if status == 200:
            print("modal is confirmed and good")
            await register_user_for_signals(interaction.user, 'VIP')
            try:
                # Attempt to send an initial response
                await interaction.response.send_message("You are now registered for VIP signals!", ephemeral=True)
            except discord.NotFound as e:
                # If the interaction is not found (probably expired), log the exception for further investigation
                print(f"Failed to respond to the interaction: {e}")
            except discord.InteractionResponded:
                # If a response has already been made, use a follow-up
                await interaction.followup.send("You are now registered for VIP signals!", ephemeral=True)
        
        elif status == 404:
            await interaction.response.send_message("Please register and be a Pro member of Coindeck to use this service.", ephemeral=True)
        elif status == 403:
            await interaction.response.send_message("You need to be a Pro member of Coindeck to use this service.", ephemeral=True)
        else:
            await interaction.response.send_message("An unexpected error occurred. Please try again later.", ephemeral=True)


async def check_email_for_vip(email):
    print(f"Making request for {email} to Coindeck...")
    url = 'https://coindeck.app/api/verify_user/'

    # Prepare the headers and data as if it was being sent by the browsable API form.
    headers = {
        'Content-Type': 'application/json',  # Set the content type to application/json
        # Add any other headers required by your API, like Authorization headers if needed.
    }
    payload = json.dumps({'email': email})  # Convert the payload to a JSON string

    async with aiohttp.ClientSession() as session:
        try:
            # Send the request with data as raw json body and the headers.
            async with session.post(url, data=payload, headers=headers) as response:
                # The rest of your code to handle the response.
                if response.status == 200:
                    response_json = await response.json()
                    print("Response is Good")
                    return response_json, 200
                else:
                    response_text = await response.text()
                    print(f"Response is not so Good {response.status} {response_text}")
                    return {"message": response_text}, response.status
        except aiohttp.ClientError as e:
            print(f"Client Error: {e}")
            return {"message": "An error occurred. Please try again later."}, 500
        
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
                follow_up_message = "You have already been registered for our Exclusive 👑VIP Signals!"
                
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


# @trading_signals_group.command(name="freesignals", description="Register for free trading signals")
# async def freesignals(ctx: discord.ApplicationContext):
#     await ctx.defer()  # This tells Discord that the bot is processing the command

#     discord_id = str(ctx.author.id)
#     # Fetch or create a user profile
#     user_profile, created = await sync_to_async(UserProfile.objects.get_or_create, thread_sensitive=True)(discord_id=discord_id)
    
#     if not created and user_profile.subscription_type == 'FREE':
#         if user_profile.received_signals_count >= 2:
#             await ctx.respond("You have exhausted your lifetime free signals. Upgrade to VIP for more exclusive signals.")
#         else:
#             await ctx.respond("You're already registered for Free Signals!")
#     else:
#         user_profile.subscription_type = 'FREE'
#         user_profile.received_signals_count = 0
#         await sync_to_async(user_profile.save, thread_sensitive=True)()
#         await ctx.respond("You've been registered for Free Signals!")

# @trading_signals_group.command(name="vipsignals", description="Register for VIP trading signals")
# async def vipsignals(ctx: discord.ApplicationContext):
#     await ctx.defer()  # This tells Discord that the bot is processing the command

#     discord_id = str(ctx.author.id)
#     # Fetch or create a user profile
#     user_profile, created = await sync_to_async(UserProfile.objects.get_or_create, thread_sensitive=True)(discord_id=discord_id)
    
#     if not created and user_profile.subscription_type == 'VIP':
#         await ctx.respond("You're already registered for VIP Signals!")
#     else:
#         user_profile.subscription_type = 'VIP'
#         await sync_to_async(user_profile.save, thread_sensitive=True)()
#         await ctx.respond("You've been upgraded to VIP Signals!")

# # Add the group to the bot's commands
# bot.add_application_command(trading_signals_group)

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

# Assuming you have a function register_user_for_signals(user, type) and check_email_for_vip(email)

pending_emails = {}  # Dictionary to keep track of users who need to input their email

@bot.event
async def on_message(message):
    if message.author == bot.user or message.guild is not None:
        return  # Ignore bot's and server messages

    user_id = message.author.id

    if '/free' in message.content.lower():
        await register_user_for_signals(message.author, 'FREE')
        response_message = f"Welcome {message.author.name}! You have been registered for free signals. Stay tuned for notifications about any Bitcoin trading opportunities."
        await message.channel.send(response_message)

    elif '/vip' in message.content.lower():
        pending_emails[user_id] = 'VIP'  # Mark the user as needing to input their email
        response_message = "Welcome! Please reply with your email to start using VIP signals."
        await message.channel.send(response_message)

    elif user_id in pending_emails:
        email = message.content  # Assume the entire message is the email
        response_json, status = await check_email_for_vip(email)  # Adjusted to await the API call
        if status == 200:
            await register_user_for_signals(message.author, 'VIP')
            await message.channel.send("You are now registered for VIP signals!")  # Adjusted for message context
        elif status == 404:
            await message.channel.send("Please register and become a Pro Member of Coindeck to use this service. Proceed to signup here https://coindeck.app/accounts/signup/")  # Adjusted
        elif status == 403:
            await message.channel.send("You need to be a Pro member of Coindeck to use this service. Kindly upgrade your profile Level!")  # Adjusted
        else:
            await message.channel.send("An unexpected error occurred. Please try again later.")  # Adjusted
        del pending_emails[user_id]  # Cleanup after handling


token = os.getenv('DISCORD_BOT_TOKEN')
bot.run(token)



