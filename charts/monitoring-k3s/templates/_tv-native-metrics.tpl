{{- define "monitoring-k3s.tvNativeMetrics" -}}
receivers:
  prometheus:
    trim_metric_suffixes: false
    config:
      scrape_configs:
        - job_name: socrat-n8n-activity
          scrape_interval: 15s
          scrape_timeout: 5s
          static_configs:
            - targets: [127.0.0.1:9189]
        - job_name: socrat-argocd
          scrape_interval: 15s
          scrape_timeout: 5s
          static_configs:
            - targets: [socrat-argocd-metrics.argocd.svc.cluster.local:8082]
{{- if .Values.publicIpProbes.enabled }}
{{- range .Values.serviceProbes.targets }}
{{- if has .id (list "edge-home" "edge-vps" "edge-moscow") }}
{{- if not (regexMatch "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+:443$" .url) }}{{ fail "Direct IP probes require literal IPv4:443 targets" }}{{ end }}
        - job_name: public-ip-{{ .id }}
          scrape_interval: 15s
          scrape_timeout: 5s
          metrics_path: /probe
          params:
            module: [direct_tcp]
            target: [{{ .url | quote }}]
          static_configs:
            - targets: [{{ printf "%s:%v" $.Values.publicIpProbes.sourceAddress $.Values.publicIpProbes.port | quote }}]
          relabel_configs:
            - target_label: job
              replacement: public-ip-probes
            - target_label: service_id
              replacement: {{ .id | quote }}
            - target_label: probe_observer
              replacement: {{ $.Values.publicIpProbes.node | quote }}
            - target_label: probe_path
              replacement: direct-home-wan
            - target_label: instance
              replacement: {{ .url | quote }}
{{- end }}
{{- end }}
{{- end }}
processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 128
  batch:
    timeout: 1s
exporters:
  otlp:
    endpoint: socrat-tv-otlp-receiver.cattle-monitoring-system.svc.cluster.local:4317
    tls:
      ca_file: /tls/ca.crt
      cert_file: /tls/tls.crt
      key_file: /tls/tls.key
      server_name_override: kube-prometheus-stack-prometheus.cattle-monitoring-system.svc
      reload_interval: 1m
    sending_queue:
      queue_size: 100
    retry_on_failure:
      max_elapsed_time: 60s
service:
  pipelines:
    metrics:
      receivers: [prometheus]
      processors: [memory_limiter, batch]
      exporters: [otlp]
{{- end -}}
