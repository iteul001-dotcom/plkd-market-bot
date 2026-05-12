# FC26 Discord Bot (Python, VS Code)

Ten folder zawiera kompletnego bota Discord do EA FC 26 Ultimate Team napisanego w Pythonie.

## 1. Co potrafi

- `/price <player>`: aktualna cena PS/XBOX/PC + trend
- `/track <player> [threshold]`: dodanie karty do watchlisty
- `/untrack <player>`: usuniecie karty z watchlisty
- `/alerts`: ostatnie alerty
- `/portfolio`: podglad portfolio
- `/toprisers` i `/topfallers`: ranking zmian
- Tracking co X minut + alerty embed
- Retry, timeout, rotacja user-agent
- Fallback: API -> HTML scraping -> simulated prices

## 2. Wymagania

- Python 3.11+
- VS Code
- VS Code extension: `Python` (Microsoft)

## 3. Instalacja krok po kroku (Windows, VS Code)

1. Otworz VS Code.
2. File -> Open Folder -> wybierz folder `futbot_py`.
3. Otworz terminal w VS Code: Terminal -> New Terminal.
4. Stworz virtual env:

```powershell
python -m venv .venv
```

5. Aktywuj virtual env:

```powershell
.venv\Scripts\Activate.ps1
```

6. Jesli masz blad execution policy, uruchom raz:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

7. Zainstaluj pakiety:

```powershell
pip install -r requirements.txt
```

8. Skopiuj env:

```powershell
copy .env.example .env
```

9. Otworz `.env` i uzupelnij:

- `DISCORD_TOKEN`
- `DISCORD_CLIENT_ID`
- `DISCORD_GUILD_ID` (polecane do szybkiego sync)
- `DISCORD_ALERT_CHANNEL_ID`

10. Uruchom bota:

```powershell
python bot.py
```

## 4. Discord setup

1. Discord Developer Portal -> New Application.
2. General Information -> skopiuj Application ID (`DISCORD_CLIENT_ID`).
3. Bot -> Add Bot -> Copy Token (`DISCORD_TOKEN`).
4. OAuth2 -> URL Generator:
- Scopes: `bot`, `applications.commands`
- Permissions: Send Messages, Embed Links, View Channels
5. Otworz wygenerowany URL i dodaj bota na serwer.
6. W Discord wlacz Developer Mode i skopiuj:
- Server ID (`DISCORD_GUILD_ID`)
- Channel ID (`DISCORD_ALERT_CHANNEL_ID`)

## 5. Komendy testowe

- `/track player:Mbappe threshold:5`
- `/price player:Mbappe`
- `/toprisers`
- `/topfallers`
- `/alerts`

## 6. Uruchomienie 24/7

Na hostingu Python uruchom command:

```bash
python bot.py
```

I ustaw wszystkie zmienne z `.env` jako Environment Variables.
