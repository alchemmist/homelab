{{/*
Image reference shared by every process in this chart.
Non-empty image.digest wins: repository@digest. Otherwise repository:tag.
*/}}
{{- define "socrat-bot.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}
{{- end -}}

{{- define "socrat-bot.components" -}}
items:
  - name: socrat-bot
    component: bot
    module: socrat_bot
    container: socrat-bot
    serviceAccount: ""
    extraEnv: true
    port: 8082
    hostNetwork: true
{{- end -}}

{{- define "socrat-bot.secretEnv" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ default .Values.envSecret .Values.databaseSecret }}
      key: DATABASE_URL
- name: TELEGRAM_BOT_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.envSecret }}
      key: TELEGRAM_BOT_TOKEN
- name: TELEGRAM_WEBHOOK_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ .Values.envSecret }}
      key: TELEGRAM_WEBHOOK_SECRET
- name: TELEGRAM_OWNER_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.envSecret }}
      key: TELEGRAM_OWNER_ID
- name: INTERNAL_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.envSecret }}
      key: INTERNAL_TOKEN
{{- end -}}

{{- define "socrat-bot.probes" -}}
readinessProbe:
  httpGet:
    path: /healthz
    port: http
  timeoutSeconds: 5
  periodSeconds: 10
  failureThreshold: 6
livenessProbe:
  httpGet:
    path: /healthz
    port: http
  timeoutSeconds: 5
  periodSeconds: 10
  failureThreshold: 6
{{- end -}}
