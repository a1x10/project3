from handlers import agents, audio, dubbing, menu, music, onboarding, profile, settings, visual, voices

# order matters: commands and navigation first, then the state-driven feature handlers
routers = [
    onboarding.router,
    menu.router,
    profile.router,
    settings.router,
    agents.router,
    audio.router,
    music.router,
    visual.router,
    voices.router,
    dubbing.router,
]
