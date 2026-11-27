{{- define "n8n.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}
{{- end -}}

{{- define "n8n.queueEnv" -}}
{{- $root := index . "root" }}
- {name: N8N_EXECUTIONS_MODE, value: queue}
- {name: QUEUE_BULL_REDIS_HOST, value: {{ $root.Values.queue.redis.host | quote }}}
- {name: QUEUE_BULL_REDIS_PORT, value: {{ $root.Values.queue.redis.port | quote }}}
- {name: QUEUE_BULL_REDIS_USERNAME, value: {{ $root.Values.queue.redis.username | quote }}}
- name: QUEUE_BULL_REDIS_PASSWORD
  valueFrom:
    secretKeyRef: {name: {{ $root.Values.queue.redis.secretName | quote }}, key: password}
{{- if $root.Values.queue.redis.tls }}
- {name: QUEUE_BULL_REDIS_TLS, value: 'true'}
{{- end }}
{{- end }}
