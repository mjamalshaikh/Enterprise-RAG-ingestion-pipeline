{{- define "rag-ingestion.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "rag-ingestion.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "rag-ingestion.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "rag-ingestion.labels" -}}
app.kubernetes.io/name: {{ include "rag-ingestion.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "rag-ingestion.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "rag-ingestion.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- required "serviceAccount.name must be supplied when serviceAccount.create is false" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
