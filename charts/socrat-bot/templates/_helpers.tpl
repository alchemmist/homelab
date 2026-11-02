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
    port: 8080
    hostNetwork: true
  - name: socrat-bot-xui-updater
    component: updater
    module: socrat_bot.updater
    container: xui-updater
    serviceAccount: socrat-bot-xui-updater
    extraEnv: false
    port: 8080
    hostNetwork: false
  - name: socrat-bot-sudo-broker
    component: broker
    module: socrat_bot.broker
    container: sudo-broker
    serviceAccount: ""
    extraEnv: false
    port: 8081
    hostNetwork: true
{{- end -}}

{{- define "socrat-bot.secretEnv" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.envSecret }}
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
livenessProbe:
  httpGet:
    path: /healthz
    port: http
{{- end -}}
