{{/* ---------------------------------------------------------------------------------
Names and labels
--------------------------------------------------------------------------------- */}}

{{- define "justforms.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "justforms.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "justforms.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "justforms.labels" -}}
helm.sh/chart: {{ include "justforms.chart" . }}
app.kubernetes.io/name: {{ include "justforms.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: justforms
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* Selector labels for one component. Usage: include "justforms.selectorLabels" (list $ "backend") */}}
{{- define "justforms.selectorLabels" -}}
{{- $root := index . 0 -}}
app.kubernetes.io/instance: {{ $root.Release.Name }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end -}}

{{- define "justforms.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "justforms.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "justforms.backendImage" -}}
{{ .Values.image.backend.repository }}:{{ .Values.image.backend.tag | default .Chart.AppVersion }}
{{- end -}}

{{- define "justforms.frontendImage" -}}
{{ .Values.image.frontend.repository }}:{{ .Values.image.frontend.tag | default .Chart.AppVersion }}
{{- end -}}

{{/* Fully qualified backend URL. nginx resolves it at runtime, without search domains. */}}
{{- define "justforms.backendUrl" -}}
{{- printf "http://%s-backend.%s.svc.%s:%v" (include "justforms.fullname" .) .Release.Namespace .Values.clusterDomain .Values.backend.port -}}
{{- end -}}

{{/* Host part of publicUrl (default Ingress / HTTPRoute host). */}}
{{- define "justforms.publicHost" -}}
{{- (urlParse .Values.publicUrl).hostname -}}
{{- end -}}

{{- define "justforms.storageClaimName" -}}
{{- .Values.storage.local.persistence.existingClaim | default (printf "%s-storage" (include "justforms.fullname" .)) -}}
{{- end -}}

{{/* "true" when local storage sits on a volume that is not ReadWriteMany. */}}
{{- define "justforms.storageIsRwo" -}}
{{- if and (eq .Values.storage.backend "local") (not (has "ReadWriteMany" .Values.storage.local.persistence.accessModes)) -}}
true
{{- end -}}
{{- end -}}

{{/* ---------------------------------------------------------------------------------
Validation: fail early on settings the backend would reject at start-up.
--------------------------------------------------------------------------------- */}}
{{- define "justforms.validate" -}}
{{- $v := .Values -}}
{{- if not $v.existingSecret -}}
{{- fail "existingSecret is required: name of a Secret with JUSTFORMS_SECRET_KEY, JUSTFORMS_DATABASE_URL and JUSTFORMS_REDIS_URL" -}}
{{- end -}}
{{- if not $v.publicUrl -}}
{{- fail "publicUrl is required (scheme://host of the app)" -}}
{{- end -}}
{{- if not (has $v.environment (list "development" "test" "production")) -}}
{{- fail (printf "environment must be development, test or production, got %q" $v.environment) -}}
{{- end -}}
{{- if not (has $v.storage.backend (list "local" "s3")) -}}
{{- fail (printf "storage.backend must be local or s3, got %q" $v.storage.backend) -}}
{{- end -}}
{{- if eq $v.storage.backend "s3" -}}
{{- if not $v.storage.s3.bucket -}}{{- fail "storage.s3.bucket is required when storage.backend is s3" -}}{{- end -}}
{{- if not $v.storage.s3.existingSecret -}}{{- fail "storage.s3.existingSecret is required when storage.backend is s3" -}}{{- end -}}
{{- end -}}
{{- if not (has $v.smtp.security (list "none" "starttls" "tls")) -}}
{{- fail (printf "smtp.security must be none, starttls or tls, got %q" $v.smtp.security) -}}
{{- end -}}
{{- if $v.auth.oidc.enabled -}}
{{- if not $v.auth.oidc.issuer -}}{{- fail "auth.oidc.issuer is required when auth.oidc.enabled is true" -}}{{- end -}}
{{- if not $v.auth.oidc.clientId -}}{{- fail "auth.oidc.clientId is required when auth.oidc.enabled is true" -}}{{- end -}}
{{- if not $v.auth.oidc.existingSecret -}}{{- fail "auth.oidc.existingSecret is required when auth.oidc.enabled is true (the backend is a confidential client)" -}}{{- end -}}
{{- end -}}
{{- if not (has $v.captcha.provider (list "none" "altcha" "turnstile" "hcaptcha")) -}}
{{- fail (printf "captcha.provider must be none, altcha, turnstile or hcaptcha, got %q" $v.captcha.provider) -}}
{{- end -}}
{{- if has $v.captcha.provider (list "turnstile" "hcaptcha") -}}
{{- if not $v.captcha.siteKey -}}{{- fail (printf "captcha.siteKey is required for captcha.provider %s" $v.captcha.provider) -}}{{- end -}}
{{- if not $v.captcha.existingSecret -}}{{- fail (printf "captcha.existingSecret is required for captcha.provider %s" $v.captcha.provider) -}}{{- end -}}
{{- end -}}
{{- if not (has ($v.branding.poweredBy | default "optional") (list "optional" "always")) -}}
{{- fail (printf "branding.poweredBy must be optional or always, got %q" $v.branding.poweredBy) -}}
{{- end -}}
{{- if not (has $v.ai.provider (list "none" "gemini" "anthropic" "openai_compat")) -}}
{{- fail (printf "ai.provider must be none, gemini, anthropic or openai_compat, got %q" $v.ai.provider) -}}
{{- end -}}
{{- if ne $v.ai.provider "none" -}}
{{- if not $v.ai.model -}}{{- fail (printf "ai.model is required for ai.provider %s" $v.ai.provider) -}}{{- end -}}
{{- if and (has $v.ai.provider (list "gemini" "anthropic")) (not $v.ai.existingSecret) -}}{{- fail (printf "ai.existingSecret is required for ai.provider %s" $v.ai.provider) -}}{{- end -}}
{{- if and (eq $v.ai.provider "openai_compat") (not $v.ai.baseUrl) -}}{{- fail "ai.baseUrl is required for ai.provider openai_compat" -}}{{- end -}}
{{- end -}}
{{- if and $v.fonts.server.configMap $v.fonts.server.secret -}}
{{- fail "fonts.server: set configMap or secret, not both" -}}
{{- end -}}
{{- if and (or $v.fonts.server.configMap $v.fonts.server.secret) (not $v.fonts.server.thaanaKey) -}}
{{- fail "fonts.server.thaanaKey is required with fonts.server.configMap or fonts.server.secret" -}}
{{- end -}}
{{- with $v.thaanaFontCssUrl -}}
{{- if not (or (hasPrefix "https://" .) (hasPrefix "/" .)) -}}
{{- fail "thaanaFontCssUrl must be an https:// URL, a /path or empty" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* ---------------------------------------------------------------------------------
Backend / worker / migrate environment. Renders envFrom (if any) then env, so callers may
append more env items right after the include.
--------------------------------------------------------------------------------- */}}

{{- define "justforms.secretEnv" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: {{ .secret }}
      key: {{ .key }}
      {{- if .optional }}
      optional: true
      {{- end }}
{{- end -}}

{{- define "justforms.backendEnv" -}}
{{- $v := .Values -}}
{{- $storage := $v.storage -}}
{{- $oidc := $v.auth.oidc -}}
{{- $keys := $v.existingSecretKeys -}}
{{- with $v.extraEnvFrom }}
envFrom:
  {{- toYaml . | nindent 2 }}
{{- end }}
env:
  # core
  - name: JUSTFORMS_PUBLIC_URL
    value: {{ $v.publicUrl | quote }}
  - name: JUSTFORMS_ENVIRONMENT
    value: {{ $v.environment | quote }}
  - name: JUSTFORMS_TIMEZONE
    value: {{ $v.timezone | quote }}
  - name: JUSTFORMS_TRUSTED_PROXIES
    value: {{ join "," $v.trustedProxies | quote }}
  - name: JUSTFORMS_MAX_UPLOAD_MB
    value: {{ $v.maxUploadMb | quote }}
  - name: JUSTFORMS_TRASH_DAYS
    value: {{ $v.trash.days | quote }}
  - name: JUSTFORMS_THAANA_FONT_CSS_URL
    value: {{ $v.thaanaFontCssUrl | quote }}
  {{- with $v.thaanaFonts }}
  - name: JUSTFORMS_THAANA_FONTS
    value: {{ join "," . | quote }}
  {{- end }}
  {{- with $v.fonts.server }}
  {{- if and (or .configMap .secret) .thaanaKey }}
  - name: JUSTFORMS_THAANA_FONT_FILE
    value: {{ printf "%s/%s" .mountPath .thaanaKey | quote }}
  {{- if .thaanaBoldKey }}
  - name: JUSTFORMS_THAANA_FONT_BOLD_FILE
    value: {{ printf "%s/%s" .mountPath .thaanaBoldKey | quote }}
  {{- end }}
  {{- end }}
  {{- end }}
  {{- if kindIs "bool" $v.cookieSecure }}
  - name: JUSTFORMS_COOKIE_SECURE
    value: {{ $v.cookieSecure | quote }}
  {{- end }}
  - name: JUSTFORMS_CORS_ORIGINS
    value: {{ join "," (default (list $v.publicUrl) $v.corsOrigins) | quote }}
  - name: JUSTFORMS_RATE_LIMIT_ENABLED
    value: {{ $v.rateLimits.enabled | quote }}
  - name: JUSTFORMS_WEBHOOK_ALLOWED_CIDRS
    value: {{ join "," $v.webhooks.allowedCidrs | quote }}
  # main Secret
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_SECRET_KEY" "secret" $v.existingSecret "key" $keys.secretKey) | nindent 2 }}
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_DATABASE_URL" "secret" $v.existingSecret "key" $keys.databaseUrl) | nindent 2 }}
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_REDIS_URL" "secret" $v.existingSecret "key" $keys.redisUrl) | nindent 2 }}
  {{- if $oidc.enabled }}
  # staff login: OIDC
  - name: JUSTFORMS_OIDC_ISSUER
    value: {{ $oidc.issuer | quote }}
  {{- with $oidc.discoveryUrl }}
  - name: JUSTFORMS_OIDC_DISCOVERY_URL
    value: {{ . | quote }}
  {{- end }}
  - name: JUSTFORMS_OIDC_CLIENT_ID
    value: {{ $oidc.clientId | quote }}
  - name: JUSTFORMS_OIDC_SCOPES
    value: {{ $oidc.scopes | quote }}
  - name: JUSTFORMS_OIDC_GROUPS_CLAIM
    value: {{ $oidc.groupsClaim | quote }}
  - name: JUSTFORMS_OIDC_ADMIN_GROUPS
    value: {{ join "," $oidc.adminGroups | quote }}
  - name: JUSTFORMS_OIDC_CREATOR_GROUPS
    value: {{ join "," ($oidc.creatorGroups | default list) | quote }}
  - name: JUSTFORMS_OIDC_MEMBER_GROUPS
    value: {{ join "," $oidc.memberGroups | quote }}
  - name: JUSTFORMS_OIDC_SUPERADMIN_GROUPS
    value: {{ join "," ($oidc.superadminGroups | default list) | quote }}
  - name: JUSTFORMS_OIDC_DEFAULT_ROLE
    value: {{ $oidc.defaultRole | default "creator" | quote }}
  - name: JUSTFORMS_OIDC_AUTO_REDIRECT
    value: {{ ternary "true" "false" (ne $oidc.autoRedirect false) | quote }}
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_OIDC_CLIENT_SECRET" "secret" $oidc.existingSecret "key" $oidc.existingSecretKey) | nindent 2 }}
  {{- end }}
  # email
  {{- with $v.smtp.host }}
  - name: JUSTFORMS_SMTP_HOST
    value: {{ . | quote }}
  {{- end }}
  - name: JUSTFORMS_SMTP_PORT
    value: {{ $v.smtp.port | quote }}
  - name: JUSTFORMS_SMTP_SECURITY
    value: {{ $v.smtp.security | quote }}
  - name: JUSTFORMS_SMTP_FROM
    value: {{ $v.smtp.from | quote }}
  {{- with $v.smtp.existingSecret }}
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_SMTP_USERNAME" "secret" . "key" $v.smtp.usernameKey "optional" true) | nindent 2 }}
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_SMTP_PASSWORD" "secret" . "key" $v.smtp.passwordKey "optional" true) | nindent 2 }}
  {{- end }}
  # file storage
  - name: JUSTFORMS_STORAGE_BACKEND
    value: {{ $storage.backend | quote }}
  {{- if eq $storage.backend "local" }}
  - name: JUSTFORMS_STORAGE_LOCAL_PATH
    value: {{ $storage.local.mountPath | quote }}
  {{- else }}
  {{- with $storage.s3.endpointUrl }}
  - name: JUSTFORMS_S3_ENDPOINT_URL
    value: {{ . | quote }}
  {{- end }}
  {{- with $storage.s3.publicEndpointUrl }}
  - name: JUSTFORMS_S3_PUBLIC_ENDPOINT_URL
    value: {{ . | quote }}
  {{- end }}
  - name: JUSTFORMS_S3_REGION
    value: {{ $storage.s3.region | quote }}
  - name: JUSTFORMS_S3_BUCKET
    value: {{ $storage.s3.bucket | quote }}
  - name: JUSTFORMS_S3_ADDRESSING_STYLE
    value: {{ $storage.s3.addressingStyle | quote }}
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_S3_ACCESS_KEY_ID" "secret" $storage.s3.existingSecret "key" $storage.s3.accessKeyIdKey) | nindent 2 }}
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_S3_SECRET_ACCESS_KEY" "secret" $storage.s3.existingSecret "key" $storage.s3.secretAccessKeyKey) | nindent 2 }}
  {{- end }}
  # signed PDFs
  {{- with $v.pdf.signingP12.existingSecret }}
  - name: JUSTFORMS_PDF_SIGNING_P12
    value: {{ printf "%s/signing.p12" $v.pdf.signingP12.mountPath | quote }}
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_PDF_SIGNING_P12_PASSWORD" "secret" . "key" $v.pdf.signingP12.passwordKey) | nindent 2 }}
  {{- end }}
  {{- with $v.pdf.tsaUrl }}
  - name: JUSTFORMS_PDF_TSA_URL
    value: {{ . | quote }}
  {{- end }}
  {{- with $v.pdf.signerName }}
  - name: JUSTFORMS_PDF_SIGNER_NAME
    value: {{ . | quote }}
  {{- end }}
  # CAPTCHA
  - name: JUSTFORMS_CAPTCHA_PROVIDER
    value: {{ $v.captcha.provider | quote }}
  {{- with $v.captcha.siteKey }}
  - name: JUSTFORMS_CAPTCHA_SITE_KEY
    value: {{ . | quote }}
  {{- end }}
  {{- if and $v.captcha.existingSecret (has $v.captcha.provider (list "turnstile" "hcaptcha")) }}
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_CAPTCHA_SECRET_KEY" "secret" $v.captcha.existingSecret "key" $v.captcha.existingSecretKey) | nindent 2 }}
  {{- end }}
  # Branding (instance defaults)
  {{- with $v.branding }}
  {{- with .name }}
  - name: JUSTFORMS_BRAND_NAME
    value: {{ . | quote }}
  {{- end }}
  {{- with .primaryColor }}
  - name: JUSTFORMS_BRAND_PRIMARY_COLOR
    value: {{ . | quote }}
  {{- end }}
  {{- with .supportUrl }}
  - name: JUSTFORMS_BRAND_SUPPORT_URL
    value: {{ . | quote }}
  {{- end }}
  - name: JUSTFORMS_BRAND_POWERED_BY
    value: {{ .poweredBy | default "optional" | quote }}
  {{- if .configMap }}
  {{- $mount := .mountPath }}
  {{- range $env, $key := dict "JUSTFORMS_BRAND_LOGO_FILE" .logoKey "JUSTFORMS_BRAND_LOGO_DARK_FILE" .logoDarkKey "JUSTFORMS_BRAND_ICON_FILE" .iconKey }}
  {{- if $key }}
  - name: {{ $env }}
    value: {{ printf "%s/%s" $mount $key | quote }}
  {{- end }}
  {{- end }}
  {{- end }}
  {{- end }}
  # AI assistant
  - name: JUSTFORMS_AI_PROVIDER
    value: {{ $v.ai.provider | quote }}
  {{- if ne $v.ai.provider "none" }}
  - name: JUSTFORMS_AI_MODEL
    value: {{ $v.ai.model | quote }}
  {{- with $v.ai.baseUrl }}
  - name: JUSTFORMS_AI_BASE_URL
    value: {{ . | quote }}
  {{- end }}
  {{- with $v.ai.visionModel }}
  - name: JUSTFORMS_AI_VISION_MODEL
    value: {{ . | quote }}
  {{- end }}
  {{- with $v.ai.vision | toString }}
  - name: JUSTFORMS_AI_VISION
    value: {{ . | quote }}
  {{- end }}
  {{- with $v.ai.providerLabel }}
  - name: JUSTFORMS_AI_PROVIDER_LABEL
    value: {{ . | quote }}
  {{- end }}
  {{- with $v.ai.dailyTokensPerUser | toString }}
  - name: JUSTFORMS_AI_DAILY_TOKENS_PER_USER
    value: {{ . | quote }}
  {{- end }}
  {{- with $v.ai.dailyTokensPerOrg | toString }}
  - name: JUSTFORMS_AI_DAILY_TOKENS_PER_ORG
    value: {{ . | quote }}
  {{- end }}
  {{- with $v.ai.existingSecret }}
  {{- include "justforms.secretEnv" (dict "name" "JUSTFORMS_AI_API_KEY" "secret" . "key" $v.ai.existingSecretKey) | nindent 2 }}
  {{- end }}
  {{- end }}
  {{- with $v.config }}
  # free-form settings (config)
  {{- range $k, $val := . }}
  - name: {{ $k }}
    value: {{ $val | quote }}
  {{- end }}
  {{- end }}
  {{- with $v.extraEnv }}
  {{- toYaml . | nindent 2 }}
  {{- end }}
{{- end -}}

{{/* volumeMounts for backend/worker/migrate. Pass (dict "root" $ "storage" bool). */}}
{{- define "justforms.appVolumeMounts" -}}
{{- $v := .root.Values -}}
volumeMounts:
  - name: tmp
    mountPath: /tmp
  {{- if and .storage (eq $v.storage.backend "local") }}
  - name: storage
    mountPath: {{ $v.storage.local.mountPath }}
  {{- end }}
  {{- if $v.pdf.signingP12.existingSecret }}
  - name: pdf-signing
    mountPath: {{ $v.pdf.signingP12.mountPath }}
    readOnly: true
  {{- end }}
  {{- if $v.branding.configMap }}
  - name: branding
    mountPath: {{ $v.branding.mountPath }}
    readOnly: true
  {{- end }}
  {{- if or $v.fonts.server.configMap $v.fonts.server.secret }}
  - name: server-fonts
    mountPath: {{ $v.fonts.server.mountPath }}
    readOnly: true
  {{- end }}
  {{- with $v.extraVolumeMounts }}
  {{- toYaml . | nindent 2 }}
  {{- end }}
{{- end -}}

{{/* Pod volumes for backend/worker/migrate. Pass (dict "root" $ "storage" bool). */}}
{{- define "justforms.appVolumes" -}}
{{- $v := .root.Values -}}
volumes:
  - name: tmp
    emptyDir: {}
  {{- if and .storage (eq $v.storage.backend "local") }}
  - name: storage
    persistentVolumeClaim:
      claimName: {{ include "justforms.storageClaimName" .root }}
  {{- end }}
  {{- with $v.pdf.signingP12.existingSecret }}
  - name: pdf-signing
    secret:
      secretName: {{ . }}
      defaultMode: 0440
      items:
        - key: {{ $v.pdf.signingP12.fileKey }}
          path: signing.p12
  {{- end }}
  {{- with $v.branding.configMap }}
  - name: branding
    configMap:
      name: {{ . }}
  {{- end }}
  {{- with $v.fonts.server.configMap }}
  - name: server-fonts
    configMap:
      name: {{ . }}
  {{- else }}
  {{- with $v.fonts.server.secret }}
  - name: server-fonts
    secret:
      secretName: {{ . }}
      defaultMode: 0444
  {{- end }}
  {{- end }}
  {{- with $v.extraVolumes }}
  {{- toYaml . | nindent 2 }}
  {{- end }}
{{- end -}}

{{/* Pod-level fields shared by every workload. Pass (dict "root" $ "c" <component values>). */}}
{{- define "justforms.podCommon" -}}
{{- $v := .root.Values -}}
{{- with $v.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .c.priorityClassName }}
priorityClassName: {{ . }}
{{- end }}
{{- with .c.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .c.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .c.topologySpreadConstraints }}
topologySpreadConstraints:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{/* ---------------------------------------------------------------------------------
Frontend CSP helpers
--------------------------------------------------------------------------------- */}}

{{/* Origins the browser reaches for presigned S3 uploads/downloads (space-separated).
     Presigned URLs use publicEndpointUrl when set, else endpointUrl. */}}
{{- define "justforms.s3Origins" -}}
{{- $s3 := .Values.storage.s3 -}}
{{- $origins := list -}}
{{- if eq .Values.storage.backend "s3" -}}
{{- $endpoint := $s3.publicEndpointUrl | default $s3.endpointUrl -}}
{{- if $endpoint -}}
{{- $u := urlParse $endpoint -}}
{{- $scheme := default "https" $u.scheme -}}
{{- if ne $s3.addressingStyle "virtual" -}}
{{- $origins = append $origins (printf "%s://%s" $scheme $u.host) -}}
{{- end -}}
{{- if ne $s3.addressingStyle "path" -}}
{{- $origins = append $origins (printf "%s://%s.%s" $scheme $s3.bucket $u.host) -}}
{{- end -}}
{{- else if eq $s3.addressingStyle "path" -}}
{{- $origins = append $origins (printf "https://s3.%s.amazonaws.com" $s3.region) -}}
{{- else -}}
{{- $origins = append $origins (printf "https://%s.s3.%s.amazonaws.com" $s3.bucket $s3.region) -}}
{{- $origins = append $origins (printf "https://%s.s3.amazonaws.com" $s3.bucket) -}}
{{- end -}}
{{- end -}}
{{- join " " $origins -}}
{{- end -}}

{{- define "justforms.cspExtraConnectSrc" -}}
{{- $all := list -}}
{{- with include "justforms.s3Origins" . -}}
{{- $all = append $all . -}}
{{- end -}}
{{- range .Values.frontend.csp.extraConnectSrc -}}
{{- $all = append $all . -}}
{{- end -}}
{{- join " " $all -}}
{{- end -}}

{{/* NetworkPolicy egress rule allowing DNS. */}}
{{- define "justforms.dnsEgress" -}}
# DNS
- to:
    - namespaceSelector:
        matchLabels:
          {{- toYaml .Values.networkPolicy.egress.dnsNamespaceSelector | nindent 10 }}
  ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
{{- end -}}
