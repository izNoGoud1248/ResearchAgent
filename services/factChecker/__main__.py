from libs.serviceRunner import ServiceRunner
from libs.settings import Settings
from services.factChecker.factCheckerApp import FactCheckerApp


class FactCheckerService:
    async def start(self) -> None:
        settings = Settings()
        await ServiceRunner.serve(FactCheckerApp(settings, settings.makeRedis()).app, settings.factCheckerUrl)


if __name__ == "__main__":
    ServiceRunner.run("factChecker", FactCheckerService().start)
