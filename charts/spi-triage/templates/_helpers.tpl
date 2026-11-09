{{- define "spi-triage.image" -}}
{{- if .Values.bundleEnabled -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest -}}
{{- else -}}
{{- .Values.legacyImage -}}
{{- end -}}
{{- end -}}
