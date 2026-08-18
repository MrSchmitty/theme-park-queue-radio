#!/usr/bin/env python3
"""
Park Radio — clip bank generator

Generates every DJ line through ElevenLabs and writes them into voices/,
along with the manifest the app reads.

Usage:
    export ELEVENLABS_API_KEY=sk_...
    python3 make-voices.py --list      # show your voices and their IDs
    python3 make-voices.py             # assign voices, then generate
    python3 make-voices.py --force     # re-record files that already exist

Safe to re-run: existing files are skipped unless --force is passed, so an
interrupted run picks up where it stopped.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.elevenlabs.io/v1"
OUT = "voices"
MAP = "voice-map.json"
MODEL = "eleven_multilingual_v2"

HOSTS = {
    "mansion":      "Mansion host",
    "skipper":      "Dock skipper",
    "dungeon":      "Dungeon pirate",
    "mining":       "Mine foreman",
    "bayou":        "Bayou announcer",
    "bellhop":      "Anthology host",
    "starport":     "Starport gate",
    "outfitter":    "Trek outfitter",
    "studio":       "Studio desk",
    "fair":         "Fair narrator",
}

# Every line is track-agnostic, so any clip fits before any piece of music.
LINES = {
    "mansion": {
        "demo": "Do come in. The gallery is rather full this evening, but I'm certain we can find room for one more.",
        "01": 'The house has selected something for you. I would not dream of interfering with its judgement.',
        "02": 'Do make yourself comfortable. Everyone does, eventually.',
        "03": 'Another room, another melody drifting out from under the door. Shall we?',
        "04": 'There is no need to hurry. We have, if nothing else, a great deal of time.',
    },
    "skipper": {
        "demo": "Afternoon, folks. We've got a full boat, a leaky engine, and absolutely no plan. Sit back and enjoy the delay.",
        "01": "Next one's coming up. I'd tell you what it is, but then you'd have no reason to keep listening.",
        "02": 'Please keep your arms and legs inside the broadcast at all times.',
        "03": "This is the part of the tour where I stop talking. Enjoy it. It doesn't last.",
        "04": "Coming up on your left, more music. Coming up on your right, also music. We're surrounded.",
    },
    "dungeon": {
        "demo": "Psst. Down here, through the bars. Ye've got the look of someone who'd help an honest man find his keys.",
        "01": "Here's a bit o' music to pass the hours. I've got nothing but hours.",
        "02": "Stay a while. The company down here's been thin lately.",
        "03": 'Ah, this one. Puts me in mind of better days and worse decisions.',
        "04": "Don't mind the noise from upstairs. They're always celebrating something.",
    },
    "mining": {
        "demo": "Last car's loaded — she runs quick out of the station, so keep your arms in and stay seated!",
        "01": "Train's away! Watch that grade, she picks up speed past the tunnel!",
        "02": "Clear the platform, we've got another one rolling out behind you!",
        "03": 'Loose rock on the ridge all week — keep sharp out there!',
        "04": "She's running hot today! Hang on and don't let go till we're stopped!",
    },
    "bayou": {
        "demo": "Settle in now and keep your hands inside the log. It's a fair way down, and the bayou don't much care whether you're ready.",
        "01": 'Sit back, folks. The current does most of the work from here.',
        "02": 'Mind the splash on the way down. Everybody comes back a little wetter than they left.',
        "03": "Take it slow through this stretch. The quiet part's the best part, if you ask me.",
        "04": 'Welcome back, now. Never doubted you for a moment.',
    },
    "bellhop": {
        "demo": 'Good evening. What follows is a recording. Ordinary enough, on the surface. You may wish to listen more closely than that.',
        "01": 'A piece of music. A quiet room. Two facts that will shortly stop agreeing with one another.',
        "02": 'You have heard this before. That is precisely the difficulty.',
        "03": 'The hour is later than you think. It usually is.',
        "04": 'Nothing unusual about the next few minutes. Nothing whatsoever. We shall see.',
    },
    "starport": {
        "demo": 'Attention travelers, departures are running on schedule, more or less. Proceed to your gate and mind the artificial gravity.',
        "01": 'Now boarding at this gate. Please have your listening credentials ready.',
        "02": "A brief announcement, followed by a much longer piece of music. You're welcome.",
        "03": 'All departures remain on time. We appreciate your continued optimism.',
        "04": 'Thank you for choosing this terminal. There were, admittedly, no other options.',
    },
    "outfitter": {
        "demo": 'Radio check from base camp. Pass is clear, weather turns by evening, and the porters say the ridge has been noisy. Pay it no mind.',
        "01": "Next stretch coming up. Steady pace, and don't look down more than you have to.",
        "02": 'Conditions are holding. Rest here while they do.',
        "03": "Signal's thin up here, but the music's getting through. That's enough.",
        "04": "You've paid for the full expedition. Might as well hear all of it.",
    },
    "studio": {
        "demo": "Hey — front desk. Studio B's been going since noon on something with a lot of strings. Grab a seat, they're nearly through.",
        "01": "Okay, next one's rolling. Don't ask me what it is, I just answer the phones.",
        "02": "They're mixing this one down the hall. Sounds better out here, honestly.",
        "03": 'Give me a second — okay. Yeah. Play it.',
        "04": "Everybody's booked solid this week, so enjoy the noise while it lasts.",
    },
    "fair": {
        "demo": 'Tomorrow is not a distant country. It is a place we are building together, one bright and orderly day at a time.',
        "01": 'And now, a demonstration of what the modern age has made possible.',
        "02": 'Listen closely. This is the sound of a century in a hurry.',
        "03": 'We stand at the threshold of something remarkable. We usually do.',
        "04": 'Progress, friends, has a melody. Here it is.',
    },
}

# Slower, heavier hosts hold together better with higher stability.
STABILITY = {
    "mansion": 0.6,
    "skipper": 0.38,
    "dungeon": 0.5,
    "mining": 0.34,
    "bayou": 0.54,
    "bellhop": 0.58,
    "starport": 0.42,
    "outfitter": 0.52,
    "studio": 0.35,
    "fair": 0.55,
}


def key():
    k = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not k:
        sys.exit("Set ELEVENLABS_API_KEY first:\n  export ELEVENLABS_API_KEY=sk_...")
    if not k.startswith("sk_"):
        print(f"Warning: key starts with {k[:3]!r}, expected 'sk_'. Continuing anyway.\n")
    return k


def request(path, data=None, headers=None, raw=False):
    url = API + path
    hdrs = {"xi-api-key": key()}
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        hdrs["content-type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read() if raw else json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        sys.exit(
            f"\nElevenLabs returned {e.code} for {path}\n{detail}\n\n"
            "401 usually means the key is wrong or lacks Voices: Read.\n"
            "429 means you've hit a rate or quota limit."
        )
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach ElevenLabs: {e.reason}")


def list_voices():
    data = request("/voices")
    return [(v["voice_id"], v.get("name", "unnamed")) for v in data.get("voices", [])]


def show_voices():
    vs = list_voices()
    if not vs:
        sys.exit("Your account has no voices yet. Create some in Voice Design first.")
    print(f"\n{len(vs)} voice(s) on this account:\n")
    for i, (vid, name) in enumerate(vs, 1):
        print(f"  {i:2}. {name:<28} {vid}")
    print()
    return vs


def assign(vs):
    if os.path.exists(MAP):
        m = json.load(open(MAP))
        missing = [h for h in HOSTS if h not in m]
        if not missing:
            print(f"Using existing assignments from {MAP}. Delete it to reassign.\n")
            return m
        print(f"{MAP} is missing {len(missing)} host(s); asking about those.\n")
    else:
        m = {}

    print("Assign a voice to each host. Enter a number, or blank to skip that host.\n")
    for h, label in HOSTS.items():
        if h in m:
            continue
        while True:
            raw = input(f"  {label:<16} 1-{len(vs)} (blank to skip): ").strip()
            if raw == "":
                break
            if raw.isdigit() and 1 <= int(raw) <= len(vs):
                m[h] = vs[int(raw) - 1][0]
                break
            print("    not a valid number")
    json.dump(m, open(MAP, "w"), indent=2)
    print(f"\nSaved to {MAP}\n")
    return m


def tts(text, voice_id, stability):
    return request(
        f"/text-to-speech/{voice_id}",
        data={
            "text": text,
            "model_id": MODEL,
            "voice_settings": {"stability": stability, "similarity_boost": 0.80},
        },
        headers={"accept": "audio/mpeg"},
        raw=True,
    )


def main():
    force = "--force" in sys.argv

    if "--list" in sys.argv:
        show_voices()
        return

    vs = show_voices()
    mapping = assign(vs)
    hosts = [h for h in HOSTS if h in mapping]
    if not hosts:
        sys.exit("No hosts assigned, nothing to do.")

    total = sum(len(LINES[h]) for h in hosts)
    chars = sum(len(t) for h in hosts for t in LINES[h].values())
    print(f"{len(hosts)} host(s), {total} clips, about {chars:,} characters.\n")

    manifest, made, skipped = {}, 0, 0
    for h in hosts:
        folder = os.path.join(OUT, h)
        os.makedirs(folder, exist_ok=True)
        entry = {"breaks": []}
        for name, text in LINES[h].items():
            fn = f"{name}.mp3"
            path = os.path.join(folder, fn)
            if os.path.exists(path) and not force:
                skipped += 1
            else:
                print(f"  {h}/{fn}")
                audio = tts(text, mapping[h], STABILITY.get(h, 0.5))
                with open(path, "wb") as f:
                    f.write(audio)
                made += 1
                time.sleep(0.4)  # stay well under the rate limit
            if name == "demo":
                entry["demo"] = fn
            else:
                entry["breaks"].append(fn)
        entry["breaks"].sort()
        manifest[h] = entry

    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDone. {made} generated, {skipped} already present.")
    print(f"Wrote {OUT}/manifest.json covering {len(manifest)} host(s).")
    print("\nTest it locally:\n  python3 -m http.server 8000")
    print("  open http://localhost:8000/park-radio.html")
    print("\nThen commit:\n  git add voices park-radio.html && git commit -m 'clip bank' && git push")


if __name__ == "__main__":
    main()
