{{- define "finedgar.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "finedgar.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "finedgar.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "finedgar.labels" -}}
app.kubernetes.io/name: {{ include "finedgar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "finedgar.selectorLabels" -}}
app.kubernetes.io/name: {{ include "finedgar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "finedgar.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "finedgar.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "finedgar.secretName" -}}
{{- default (printf "%s-secrets" (include "finedgar.fullname" .)) .Values.secrets.existingSecret -}}
{{- end -}}

{{- define "finedgar.postgresHost" -}}
{{- if .Values.postgres.cnpg.enabled -}}
{{- printf "%s-postgres-rw" (include "finedgar.fullname" .) -}}
{{- else -}}
{{- printf "%s-postgres" (include "finedgar.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "finedgar.databaseUrl" -}}
{{- printf "postgresql+asyncpg://%s:%s@%s:5432/%s" .Values.postgres.user .Values.postgres.password (include "finedgar.postgresHost" .) .Values.postgres.database -}}
{{- end -}}
