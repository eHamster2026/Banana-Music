"""Run once to populate the database with demo data."""
from database import SessionLocal, engine
import models

models.Base.metadata.create_all(bind=engine)

from auth_utils import get_password_hash
from config import settings

ARTISTS = [
    {"name": "The Weeknd",     "art_color": "art-1",  "bio": "来自加拿大的 R&B 天王",           "monthly_listeners": 85_000_000},
    {"name": "Ariana Grande",  "art_color": "art-2",  "bio": "流行天后，嗓音横跨三个八度",       "monthly_listeners": 78_000_000},
    {"name": "Dua Lipa",       "art_color": "art-3",  "bio": "英国流行女王",                    "monthly_listeners": 72_000_000},
    {"name": "Taylor Swift",   "art_color": "art-4",  "bio": "乡村流行跨界天后",                "monthly_listeners": 90_000_000},
    {"name": "Drake",          "art_color": "art-5",  "bio": "힙합 & R&B 巨星",                "monthly_listeners": 68_000_000},
    {"name": "Billie Eilish",  "art_color": "art-6",  "bio": "暗黑流行代言人",                  "monthly_listeners": 62_000_000},
    {"name": "Travis Scott",   "art_color": "art-7",  "bio": "Houston 说唱先锋",               "monthly_listeners": 55_000_000},
    {"name": "SZA",            "art_color": "art-8",  "bio": "R&B 新生代女王",                 "monthly_listeners": 48_000_000},
]

ALBUMS = [
    # (title, artist_idx, art_color, release_date, type)
    ("After Hours",       0, "art-1",  "2020-03-20", "album"),
    ("Starboy",           0, "art-9",  "2016-11-25", "album"),
    ("Positions",         1, "art-2",  "2020-10-30", "album"),
    ("Thank U, Next",     1, "art-10", "2019-02-08", "album"),
    ("Future Nostalgia",  2, "art-3",  "2020-03-27", "album"),
    ("Midnights",         3, "art-4",  "2022-10-21", "album"),
    ("Certified Lover",   4, "art-5",  "2021-09-03", "album"),
    ("Her Loss",          4, "art-11", "2022-11-04", "album"),
    ("Happier Than Ever", 5, "art-6",  "2021-07-30", "album"),
    ("Utopia",            6, "art-7",  "2023-07-28", "album"),
    ("SOS",               7, "art-8",  "2022-12-09", "album"),
    ("Chromatica",        1, "art-12", "2020-05-29", "album"),
]

# 5 tracks per album  (title, duration_sec, track_number)
TRACKS_TPL = [
    [
        ("Blinding Lights",      200, 1), ("In Your Eyes",         232, 2),
        ("Save Your Tears",      215, 3), ("Heartless",            188, 4), ("Alone Again",         239, 5),
    ],
    [
        ("Starboy",              230, 1), ("I Feel It Coming",     223, 2),
        ("Reminder",             218, 3), ("Rockin",               198, 4), ("Nothing Without You", 201, 5),
    ],
    [
        ("Positions",            172, 1), ("34+35",                174, 2),
        ("Motive",               196, 3), ("Off the Table",        249, 4), ("Six Thirty",          195, 5),
    ],
    [
        ("thank u, next",        207, 1), ("break up with your gf", 190, 2),
        ("7 rings",              178, 3), ("NASA",                 197, 4), ("Fake Smile",          219, 5),
    ],
    [
        ("Levitating",           203, 1), ("Don't Start Now",      183, 2),
        ("Physical",             194, 3), ("Break My Heart",       222, 4), ("Pretty Please",       209, 5),
    ],
    [
        ("Lavender Haze",        202, 1), ("Marjorie",             265, 2),
        ("Anti-Hero",            200, 3), ("Snow on the Beach",    270, 4), ("Bejeweled",           195, 5),
    ],
    [
        ("Champagne Poetry",     296, 1), ("TSU",                  181, 2),
        ("Girls Want Girls",     199, 3), ("IMY2",                 192, 4), ("Fair Trade",          316, 5),
    ],
    [
        ("Rich Flex",            213, 1), ("Major Distribution",   224, 2),
        ("On BS",                172, 3), ("Privileged Rappers",   256, 4), ("Circo Loco",          307, 5),
    ],
    [
        ("Happier Than Ever",    295, 1), ("Getting Older",        236, 2),
        ("Lost Cause",           215, 3), ("Therefore I Am",       172, 4), ("Your Power",          247, 5),
    ],
    [
        ("HYAENA",               200, 1), ("THANK GOD",            197, 2),
        ("MY EYES",              192, 3), ("FE!N",                 202, 4), ("CIRCUS MAXIMUS",      327, 5),
    ],
    [
        ("SOS",                  215, 1), ("Shirt",                221, 2),
        ("Kill Bill",            153, 3), ("Seek & Destroy",       219, 4), ("Low",                 218, 5),
    ],
    [
        ("Chromatica I",          57, 1), ("Alice",                210, 2),
        ("Stupid Love",          194, 3), ("Rain on Me",           213, 4), ("Free Woman",          218, 5),
    ],
]

PLAYLISTS = [
    ("Today's Hits",   "art-1",  True,  True,  "今日最热单曲合集"),
    ("深夜爵士",        "art-5",  True,  True,  "宁静夜晚的最佳伴侣"),
    ("Workout Beats",  "art-3",  True,  True,  "让你燃起来的运动歌单"),
    ("周末清晨",        "art-9",  True,  True,  "慵懒周末的清晨心情"),
    ("Pop Rising",     "art-8",  True,  True,  "崭露头角的流行新星"),
    ("Hip-Hop 精选",   "art-10", True,  True,  "嘻哈文化精华合集"),
]

BANNERS = [
    ("Midnight Echoes",     "The Weeknd · 全新专辑现已上线",  "新专辑",          "art-1",  "立即播放",  "album",    1),
    ("Today's Hits",        "精心策划 · 每日更新",            "Apple Music 精选", "art-5",  "开始收听",  "playlist", 1),
    ("Apple Music Live",    "Bruno Mars · 独家演唱会直播",     "现场直播",        "art-3",  "即将开始",  "playlist", 2),
]

SOUNDHELIX = [
    f"https://www.soundhelix.com/examples/mp3/SoundHelix-Song-{i}.mp3"
    for i in range(1, 18)
]

LYRICS_SAMPLE = """[00:00.00] 演示歌词第一行
[00:05.00] 音乐响起 夜色弥漫
[00:10.00] 光影交错 心跳加速
[00:15.00] 在这一刻 所有烦恼消散
[00:20.00] 旋律带我走向远方
[00:25.00] 此刻只有音乐与你
"""


def seed():
    db = SessionLocal()
    try:
        if db.query(models.User).count() > 0:
            print("数据库已有数据，跳过 seed。")
            return

        # Demo user
        demo_user = models.User(
            username=settings.demo_username,
            email=settings.demo_email,
            hashed_password=get_password_hash(settings.demo_password),
            avatar_color="art-1",
            is_admin=True,
        )
        db.add(demo_user)
        db.flush()

        # Artists
        artist_objs = []
        for a in ARTISTS:
            obj = models.Artist(**a)
            db.add(obj)
            artist_objs.append(obj)
        db.flush()

        # Albums + Tracks
        track_counter = 0
        for i, (title, artist_idx, art_color, release_date, album_type) in enumerate(ALBUMS):
            album = models.Album(
                title=title, artist_id=artist_objs[artist_idx].id,
                art_color=art_color, release_date=release_date, album_type=album_type,
            )
            db.add(album)
            db.flush()
            for t_title, duration, track_number in TRACKS_TPL[i]:
                stream_url = SOUNDHELIX[track_counter % len(SOUNDHELIX)]
                track = models.Track(
                    title=t_title, album_id=album.id,
                    artist_id=artist_objs[artist_idx].id,
                    duration_sec=duration, track_number=track_number,
                    stream_url=stream_url,
                    lyrics=LYRICS_SAMPLE if track_number == 1 else None,
                )
                db.add(track)
                track_counter += 1
        db.flush()

        # System playlists
        all_tracks = db.query(models.Track).all()
        for name, art_color, is_featured, is_system, desc in PLAYLISTS:
            pl = models.Playlist(
                name=name, art_color=art_color,
                is_featured=is_featured, is_system=is_system,
                description=desc, user_id=None,
            )
            db.add(pl)
            db.flush()
            import random
            chosen = random.sample(all_tracks, min(10, len(all_tracks)))
            for pos, t in enumerate(chosen):
                pt = models.PlaylistTrack(playlist_id=pl.id, track_id=t.id, position=pos)
                db.add(pt)

        # Banners
        playlists = db.query(models.Playlist).all()
        albums = db.query(models.Album).all()
        for i, (title, subtitle, badge, art_color, btn_text, target_type, target_id) in enumerate(BANNERS):
            real_id = albums[i % len(albums)].id if target_type == "album" else playlists[i % len(playlists)].id
            banner = models.Banner(
                title=title, subtitle=subtitle, badge=badge,
                art_color=art_color, btn_text=btn_text,
                target_type=target_type, target_id=real_id, sort_order=i,
            )
            db.add(banner)

        db.commit()
        print(f"✅ Seed 完成！演示账号: {settings.demo_username} / {settings.demo_password}")
    except Exception as e:
        db.rollback()
        print(f"❌ Seed 失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
