import os
import re
import sys
import json
import time
import email
import imaplib
import subprocess
from typing import Union
from datetime import date
from multiprocessing import Process, Queue

import requests
from youtube_dl import YoutubeDL

from getyotubeid import get_youtube_id


def check_ffmpeg() -> int:
    """Check the is the ffmpeg available or not.

    Returns:
        int: 0 if not found, 1 if locally, 2 if system wide.
    """

    with open(os.devnull, 'w') as NULL:
        # Check system wide.
        try:
            _ = subprocess.run(('ffmpeg', '-version'), stdout=NULL)
            _ = subprocess.run(('ffprobe', '-version'), stdout=NULL)
        except:
            pass
        else:
            return 2

        # Check locally.
        dir_list = os.listdir()

        if 'ffmpeg' in dir_list:
            try:
                _ = subprocess.run(('./ffmpeg', '-version'), stdout=NULL)
                _ = subprocess.run(('./ffprobe', '-version'), stdout=NULL)
            except:
                pass
            else:
                return 1
        elif 'ffmpeg.exe' in dir_list:
            try:
                _ = subprocess.run(('./ffmpeg.exe', '-version'), stdout=NULL)
                _ = subprocess.run(('./ffprobe.exe', '-version'), stdout=NULL)
            except:
                pass
            else:
                return 1

    return 0

def init_mail_settings() -> tuple:
    """Initailize the the email settings.

    Returns:
        tuple: The email credentials and settings. (user, pass, port, ssl)
    """

    mail_user = os.getenv('MAIL2MP3_USER', default=None)
    mail_pass = os.getenv('MAIL2MP3_PASS', default=None)
    mail_host = os.getenv('MAIL2MP3_HOST', default='imap.gmail.com')
    mail_port = os.getenv('MAIL2MP3_PORT', default=None)
    mail_ssl = os.getenv('MAIL2MP3_SSL', default=True)

    return (mail_user, mail_pass, mail_host, mail_port, mail_ssl)

def get_mail(connection: Union[imaplib.IMAP4, imaplib.IMAP4_SSL], mail_id: int) -> Union[dict, None]:
    """Fetch the mail with the given ID.

    The whole method is in a try block, because all the steps can change.

    Args:
        connection (Union[imaplib.IMAP4, imaplib.IMAP4_SSL]): Active connection to the server.
        mail_id (int): ID of the mail.

    Returns:
        (Union[dict, None]): dict if successfully fetch and parse the mail else None.
    """

    email_address_pattern = re.compile(r'\w[\w\.]*@[\w\.]+\.\w+')

    try:
        return_code, data = connection.fetch(mail_id, '(RFC822)')

        if return_code != 'OK':
            return None

        messabe_object = email.message_from_bytes(data[0][1])

        parsed_mail = {
            'from': email_address_pattern.findall(messabe_object['Return-Path'])[0],
            'subject': messabe_object['Subject'],
            'body': '',
        }

        # If the body content is multipart we have to iterate over the parts (e.g.: plain text + html)
        for part in messabe_object.get_payload():
            parsed_mail['body'] += part.get_payload() + '\n'

        return parsed_mail

    except:
        return None

def handle_shazam(mail_body: str) -> Union[str, None]:
    """Extract the youtube ID from a shazam share mail.

    Args:
        mail_body (str): Body of the shazam share mail.

    Returns:
        (Union[str, None]): The youtube ID or None.
    """

    shazam_track_url = 'https://www.shazam.com/discovery/v4/en-US/HU/web/-/track/'

    shazam_url_patterns = [
        re.compile(r'shazam\.com\/track\/\d+#'),
        re.compile(r'shz\.am\/t\d+'),
    ]
    shazam_id_pattern = re.compile('\d+')

    shazam_url = None

    for pattern in shazam_url_patterns:
        urls = pattern.findall(mail_body)

        if len(urls) > 0:
            shazam_url = urls[0]
            break

    if not shazam_url:
        return None

    shazam_id = shazam_id_pattern.findall(shazam_url)
    if len(shazam_id) == 0:
        return None

    shazam_id = shazam_id[0]

    response = requests.get(shazam_track_url + shazam_id)
    if response.status_code != 200:
        return None

    try:
        response = json.loads(response.text)

        url = None
        for feed in response['feed']:
            if feed['id'] == 'generalvideos':
                for action in feed['actions']:
                    if action['type'] == 'youtubeplay':
                        url = action['href']

        if not url:
            return None

        response = requests.get(url)
        if response.status_code != 200:
            return None

        response = json.loads(response.text)

        url = None
        youtube_id = response['youtube']['videos'][0]['id']

        return youtube_id

    except Exception as e:
        print('[ERROR] Cannot get YouTube ID from Shazam email.', e)

        return None

def create_out_dir(from_mail: str) -> tuple:
    """Create the output dir if not exists for the download.

    Args:
        from_mail (str): Email address of the sender.

    Returns:
        tuple: (True | False, path [str]). True if exists or created, False if cannot.
    """

    path = os.path.join('output', from_mail, str(date.today().year) + '_' + str(date.today().month))

    if os.path.exists(path):
        return (True, path)

    try:
        os.makedirs(path)
    except:
        return (False, path)
    else:
        return (True, path)

def process_mail(queue: Queue, ffmpeg_location: int) -> None:
    """Get an email from the queue and process it forever.

    Args:
        queue (Queue): The queue which contains the emails.
        ffmpeg_location (int): 1 if locally found, 2 if system wide.
    """

    # Run forever.
    while True:
        mail = queue.get()

        # If no mail, take a sleep.
        if not mail:
            time.sleep(5)

        # Check the type. Default is YouTube.
        # If we found youtube ID in the subject or in the body -> youtube
        # If not found -> shazam
        share_source = 'youtube'
        youtube_id = None

        if mail['subject']:
            youtube_id = get_youtube_id(mail['subject'])

        if not youtube_id and mail['body']:
            youtube_id = get_youtube_id(mail['body'])

        # If we still not have any youtube id, it should be a shazam share.
        if not youtube_id:
            youtube_id = handle_shazam(mail['body'])
            share_source = 'shazam'

        if not youtube_id:
            print('[INFO] Cannot parse mail from {} with subject {}.'.format(mail['from'], mail['subject']))
            return

        out_exists, out_path = create_out_dir(mail['from'])
        if not out_exists:
            print('[ERROR] Cannot create dir:', out_path)
            return

        ytdl_opts = {
            'quiet': True,
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(out_path, '%(title)s.m4a'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }]
        }

        if ffmpeg_location == 1:
            ytdl_opts['ffmpeg_location'] = os.path.dirname(os.path.realpath(__file__))

        with YoutubeDL(ytdl_opts) as ytdl:
            video_info = ytdl.extract_info('https://www.youtube.com/watch?v=' + youtube_id)
            youtube_title = video_info.get('title', 'Unknown title')
            ytdl.download(['https://www.youtube.com/watch?v=' + youtube_id])

            if share_source == 'shazam':
                print('[INFO] Download finished for\r\n \
                        Shazam name:\t{}\r\n \
                        Youtube name:\t{}\r\n' \
                        .format(mail['subject'], youtube_title))
            elif share_source == 'youtube':
                print('[INFO] Download finished for\r\n \
                        Youtube name:\t{}\r\n' \
                        .format( youtube_title))

def start_listening(
    username: str,
    password: str,
    host: str,
    port: Union[str, None],
    ssl: bool,
    ffmpeg_location: int) -> None:
    """Start listening on the IMAP protocol for unseen email messages.

    Args:
        username (str): Email username.
        password (str): Email password.
        host (str): Hostname of the email service.
        port (Union[str, None]): Port in str if given, else None.
        ssl (bool): True if use SSL, False if not.
        ffmpeg_location (int): 1 if locally found, 2 if system wide.
    """

    # Connection to the mail.
    connection = None

    # Try to log in.
    try:
        if ssl:
            port = int(port) if port else imaplib.IMAP4_SSL_PORT
            connection = imaplib.IMAP4_SSL(host=host, port=port)
        else:
            port = int(port) if port else imaplib.IMAP4_PORT
            connection = imaplib.IMAP4_SSL(host=host, port=port)

        connection.login(username, password)

    except Exception as e:
        print('[ERROR] Cannot login to the email account.', e)
        sys.exit()

    print('[INFO] Successfully connected to ' + username + '.')

    # TODO: custom mailbox.
    # Get the default mailbox. This is INBOX in Gmail.
    connection.select()

    # Create the queue for the emails.
    queue = Queue()

    # Start the email processing processes
    for i in range(os.cpu_count()):
        p = Process(target=process_mail, args=(queue, ffmpeg_location), daemon=True)
        p.start()

    # Loop forever to looking for unseen emails.
    while True:
        return_code, data = connection.search(None, '(UNSEEN)')

        if return_code != 'OK':
            print('[ERROR] Cannot search for emails! Return code:', return_code)
            time.sleep(10)
            continue

        mail_ids = data[0].decode('utf-8')
        if mail_ids == '':
            print('[INFO] No email found. ZzZZZz...')
            time.sleep(10)
            continue

        mail_ids = mail_ids.split(' ')

        if len(mail_ids) > 0:
            print('[INFO] Found {} email(s).'.format(len(mail_ids)))

            # Get the mails.
            for mail_id in mail_ids:
                mail = get_mail(connection, mail_id)

                if mail is not None:
                    queue.put(mail)

        # Relax a bit.
        time.sleep(10)

def main() -> None:
    # Let's check if we have FFmpeg.
    ffmpeg_location = check_ffmpeg()
    if ffmpeg_location == 0:
        print('[ERROR] Cannot find FFmpeg.')
        sys.exit()
    else:
        print('[INFO] FFmpeg found.')

    # Init the email settings.
    email_settings = init_mail_settings()

    # If we not have email user or pass, terminate the code.
    if email_settings[0] is None or email_settings[1] is None:
        print('[ERROR] Email username or/and password is missing.')
        sys.exit()

    # Start the core.
    start_listening(
        username=email_settings[0],
        password=email_settings[1],
        host=email_settings[2],
        port=email_settings[3],
        ssl=email_settings[4],
        ffmpeg_location=ffmpeg_location
    )

if __name__ == '__main__':
    main()