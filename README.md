# WUWA Tracker

A small Windows app that keeps track of everything you want to get done in Wuthering Waves every day, week and month.
Tick things off as you go. Everything resets by itself with the server reset, so you always know what is still left.

I made it for myself and a few friends. It is free, open source and not affiliated with Kuro Games.

## What it does

- Daily, weekly and monthly task lists that reset with your server (Europe, America, Asia, SEA, HMT)
- Waveplate and Waveplate Crystal counters, with an alert shortly before your Waveplate is full
- Nightmare Nests and weekly bosses you can tick off one by one
- Banner countdowns and a Lunite Subscription timer
- A reminder before the daily reset if something is still open
- An optional see-through overlay that stays on top of the game (hold ALT to click it)
- One-click updates straight from this page

You can add your own tasks, rename them, drag them into a different order or remove them.

## Download

Get `WUWA-Tracker-Setup.exe` from the [latest release](../../releases/latest) and run it.

Good to know:
- Windows SmartScreen may warn you because the app is not code-signed. Click **More info**, then **Run anyway**.
- The app asks for administrator rights when it starts. The game usually runs with administrator rights, and without the same rights Windows does not let the overlay see the ALT key.
- It needs the Microsoft WebView2 Runtime, which is already installed on almost every Windows 10/11 PC.

## Your data

Everything stays on your PC in `%APPDATA%\WuWaTracker`: your progress, your task list (`tasks.json`) and an `error.log` if something goes wrong.
The app only goes online to check this page for a new version (you can turn that off in the settings) and, when you click the update banner, to download it.

## Building it yourself

You need Python 3.12 or newer. Run `build.bat`: it builds the app with PyInstaller and, if Inno Setup is installed, the installer too.
Every change pushed here is also built automatically by GitHub Actions.

## Bugs and ideas

Open an [issue](../../issues) and describe what happened. Attaching your `error.log` helps a lot.

## License

MIT, see [LICENSE](LICENSE).
