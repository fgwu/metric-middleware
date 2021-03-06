from crystal_metric_middleware.metrics.abstract_metric import AbstractMetric


class GetActiveRequestsContainer(AbstractMetric):

    def execute(self):
        """
        Execute Metric
        """
        self.type = 'stateful'

        if self.method == "GET" and self._is_object_request():
            self._intercept_get()
            self.register_metric(self.account_and_container, 1)

        return self.response

    def on_finish(self):
        self.register_metric(self.account_and_container, -1)
