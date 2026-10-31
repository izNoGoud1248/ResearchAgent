class ModelRouter:
    def __init__(
        self,
        cheapModel: str,
        strongModel: str,
        strongTasks: frozenset[str] = frozenset({"writer"}),
        longPrompt: int = 24000,
    ):
        self.cheapModel = cheapModel
        self.strongModel = strongModel
        self.strongTasks = strongTasks
        self.longPrompt = longPrompt

    def pick(self, task: str, promptLength: int) -> str:
        if task in self.strongTasks or promptLength > self.longPrompt:
            return self.strongModel
        return self.cheapModel
