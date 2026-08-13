# legacy batch data pipeline skeleton (to be evolved into a real framework)
class Stage:
    def __init__(self, name):
        self.name = name

    def run(self, rows):
        raise NotImplementedError


class Source(Stage):
    def __init__(self, name, data):
        super().__init__(name)
        self.data = list(data)

    def run(self, rows):
        return self.data


class Sink(Stage):
    def __init__(self, name):
        super().__init__(name)
        self.rows = []

    def run(self, rows):
        self.rows.extend(rows)
        return []


class Pipeline:
    def __init__(self):
        self.stages = []

    def add(self, stage):
        self.stages.append(stage)
        return self

    def run(self, initial=None):
        rows = list(initial or [])
        for stage in self.stages:
            rows = stage.run(rows)
        return rows
