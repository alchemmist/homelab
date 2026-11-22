# Tracing with Tempo

Tempo stores traces from instrumented services. If you have a trace ID, look it up in Grafana's Tempo data source and inspect the spans for the failing or slow operation. A log entry or metric alone does not prove that the request emitted a trace.

For deployment or storage questions, start with the [Tempo Argo CD Application](../../../deploy/argocd/apps/tempo.yaml) and its [Helm chart](../../../charts/tempo/). For log delivery rather than trace lookup, use the [logging guide](../logging/operator-guide.md).
