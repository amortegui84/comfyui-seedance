# Skill: Video Generation API Expert

> Instala este archivo en el folder del nodo. Úsalo como contexto de referencia experta para cualquier trabajo con AnyFast, fal.ai, Replicate, u otros proveedores de generación de video/imagen via API asíncrona en ComfyUI.

---

## 1. Patrón general — APIs de generación asíncrona

Todos los proveedores (AnyFast, fal.ai, Replicate) siguen el mismo patrón de tres pasos:

```
SUBMIT → POLL → RETRIEVE
  POST      GET loop     GET/extract URL
```

### 1.1 Submit

```python
r = requests.post(endpoint, json=payload, headers=auth_headers, timeout=(30, 600))
# timeout=(connect, read): el connect debe ser corto, el read largo para payloads grandes
task_id = r.json()["id"]  # o "request_id", "prediction_id" según proveedor
```

**Regla crítica:** nunca usar un timeout plano para submits con imágenes en base64 — el payload puede ser grande. Usar `timeout=(connect_secs, read_secs)`.

### 1.2 Poll

```python
time.sleep(initial_wait)   # esperar antes del primer poll (3-5s típico)
while time.time() < deadline:
    r = requests.get(f"{base_url}/{task_id}", headers=auth_headers, timeout=30)
    r.raise_for_status()
    status = extract_status(r.json())
    if status in DONE_STATES:
        return extract_url(r.json())
    if status in FAIL_STATES:
        raise RuntimeError(extract_error(r.json()))
    time.sleep(interval)   # 5s típico
raise TimeoutError(...)
```

**Regla:** los estados de éxito y fallo varían por proveedor — ver sección 2. Siempre lowercase antes de comparar.

### 1.3 Extracción robusta de URLs y estados

Las APIs cambian schemas sin avisar. Usar un walker que recorra el JSON en BFS:

```python
def walk_dicts(root, max_depth=6):
    queue = [(root, 0)]
    while queue:
        current, depth = queue.pop(0)
        yield current
        if depth >= max_depth:
            continue
        for v in current.values():
            if isinstance(v, dict):
                queue.append((v, depth + 1))
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        queue.append((item, depth + 1))
```

Buscar `video_url`, `url`, `result_url` en cualquier dict del árbol. Esto resiste cambios de schema.

---

## 2. AnyFast

**Base URL:** `https://www.anyfast.ai`  
**Auth header:** `Authorization: Bearer {api_key}`  
**Content-Type:** `application/json`

### 2.1 Seedance 2.0 — Generation

**Endpoint:** `POST /v1/video/generations`

```json
{
  "model": "seedance",           // o "seedance-fast" / "seedance-2.0-ultra"
  "content": [
    {"type": "text", "text": "..."},
    {"type": "image_url", "image_url": {"url": "asset://id-or-data-uri"}, "role": "first_frame"}
  ],
  "resolution": "720p",         // seedance/fast: 480p|720p|1080p  ultra: 720p|1080p|2k
  "ratio": "adaptive",          // 16:9|9:16|4:3|3:4|1:1|21:9|adaptive
  "duration": 5,                // 4-15 segundos
  "generate_audio": true,
  "watermark": false
}
```

**Roles en content:**
- `first_frame` — primera imagen del video (image_url)
- `last_frame` — última imagen del video (image_url)
- `reference_image` — referencia de estilo/contenido, hasta 9 (image_url); requiere `@image1`…`@imageN` en prompt
- `reference_video` — video de referencia, hasta 3 (video_url); requiere `@video1` en prompt
- `reference_audio` — audio de referencia, hasta 3 (audio_url); requiere `@audio1` en prompt

**Límites por tipo:**
- Imágenes: máx 30 MB por imagen, máx 9 por request
- Video: máx 50 MB, duración 2-15s, máx 3 por request
- Audio: máx 15 MB, duración 2-15s, máx 3 por request; **debe acompañar al menos una imagen o video**

**URL formats para imágenes:**
- `asset://asset-id` — asset ya subido (lowercase, confirmado por docs del endpoint de generación)
- `data:image/png;base64,...` — base64 data URI
- `https://...` — URL pública

**Submit response:**
```json
{"id": "cgt-xxx", "task_id": "cgt-xxx", "object": "video", "model": "seedance", "status": "", "progress": 0, "created_at": 1234}
```

**Polling:** `GET /v1/video/generations/{id}`

**Poll response structure:**
```json
{
  "code": "success",
  "message": "...",
  "data": {
    "task_id": "...",
    "status": "QUEUING|PROCESSING|SUCCESS|FAILED",
    "fail_reason": "mensaje de error cuando FAILED",
    "progress": "75%",
    "data": {
      "content": {
        "video_url": "https://... (24h validity)"
      }
    }
  }
}
```

**Estados de poll:** `QUEUING` → `PROCESSING` → `SUCCESS` | `FAILED` (siempre uppercase — normalizar a lowercase al comparar)

**Gotcha importante:** el video URL está en `body.data.data.content.video_url` (anidado 4 niveles). Usar BFS walker.

### 2.2 AnyFast Asset Management

El flujo de assets es **obligatorio** para images como `first_frame` en generación. Los assets necesitan alcanzar estado `Active` antes de poder usarse.

**Flujo completo:**

```
CreateAssetGroup → CreateAsset → ListAssets (poll hasta Active) → usar en generación
```

#### CreateAssetGroup

`POST /volc/asset/CreateAssetGroup`

```json
{"model": "volc-asset", "Name": "nombre-grupo"}
```

Response: `{"Id": "group-xxx"}`

- El campo se llama `Id` (capital I, minúscula d)
- **NO tiene campo GroupType** — los grupos se crean sin tipo

#### CreateAsset

`POST /volc/asset/CreateAsset`

**JSON (imágenes — preferido):**
```json
{
  "model": "volc-asset",
  "GroupId": "group-xxx",    // REQUERIDO
  "Name": "nombre",
  "AssetType": "Image",      // REQUERIDO: Image | Video | Audio
  "URL": "data:image/png;base64,..."   // URL pública, data URI, o base64 raw
}
```

**Multipart (video/audio):**
```
model=volc-asset-video  (o volc-asset-audio)
GroupId=group-xxx        REQUERIDO
Name=nombre
AssetType=Video          REQUERIDO (default sería "Image" si se omite — bug silencioso)
file=<bytes>
```

**Modelos por tipo (billing):**
- Image → `volc-asset`
- Video → `volc-asset-video`
- Audio → `volc-asset-audio`

Response: `{"Id": "asset-xxx"}` — el campo se llama `Id`

**Gotcha:** `GroupId` es REQUERIDO en JSON (la doc lo marca explícitamente). Sin él → 400.

#### ListAssets — polling para estado Active

`POST /volc/asset/ListAssets`

```json
{
  "model": "volc-asset",
  "Filter": {
    "GroupIds": ["group-xxx"]
    // NO incluir GroupType — los grupos no tienen tipo asignado
  },
  "PageNumber": 1,
  "PageSize": 100
}
```

Response items: `{"Id": "asset-xxx", "Status": "Active", "AssetType": "Image", ...}`

**Gotcha crítico:** filtrar por `GroupType` (ej: `"AIGC"`) retorna `Items: []` porque los grupos se crean sin tipo. Omitir siempre ese filtro.

**Poll logic:**
```python
while time.time() < deadline:
    items = list_assets(group_id)
    for item in items:
        if item["Id"] == asset_id and item["Status"] == "Active":
            return  # listo para usar
    time.sleep(5)
raise RuntimeError("Asset no alcanzó Active en tiempo")
```

**Timeout recomendado:** 300s (5 min). El processing puede tomar tiempo variable.

### 2.3 AnyFast — Patrones anti-error

| Síntoma | Causa probable | Fix |
|---|---|---|
| `"The specified asset X is not found"` en generación | Asset no está Active todavía | Hacer poll ListAssets hasta Status=Active |
| `ListAssets` siempre retorna `Items: []` | Filtro `GroupType` incorrecto | Remover GroupType del filter |
| `CreateAsset 400 group not found` | Grupo recién creado no propagado | Retry con delay (4s×3) |
| `CreateAsset` falla con video/audio | AssetType no enviado, defaultea a Image | Siempre enviar AssetType explícito |
| Error de generación sin mensaje útil | `fail_reason` no extraído | Buscar en `body.data.fail_reason` |

---

## 3. fal.ai

**Base URL submit:** `https://queue.fal.run`  
**Base URL result:** `https://queue.fal.run` (mismo dominio)  
**Auth header:** `Authorization: Key {api_key}` (no Bearer — es `Key`)

### 3.1 Queue API

**Submit:**
```
POST https://queue.fal.run/{app_id}
Authorization: Key {key}
Content-Type: application/json

{payload}
```

Response:
```json
{"request_id": "xxx", "response_url": "...", "status_url": "...", "cancel_url": "...", "queue_position": 0}
```

**Poll status:**
```
GET https://queue.fal.run/fal-ai/queue/requests/{request_id}/status
```

Estados: `IN_QUEUE` → `IN_PROGRESS` → `COMPLETED`

**Gotcha:** en fal.ai los estados son UPPERCASE con underscore. Diferente a Replicate y AnyFast.

**Retrieve result:**
```
GET https://queue.fal.run/fal-ai/queue/requests/{request_id}
```

El video URL está en `r.json()["video"]["url"]` para modelos de video (estructura model-specific).

### 3.2 fal.ai Seedance endpoints

**App ID pattern:** `bytedance/seedance-2.0/{variant}` donde variant:
- `text-to-video` — T2V
- `image-to-video` — I2V (first_frame)
- `fast/text-to-video` — fast T2V
- `fast/image-to-video` — fast I2V
- `reference-to-video` — con referencias (imagen + video + audio)

**Campos clave para imagen:**
- `image_url` → first frame (string URL o data URI)
- `end_image_url` → last frame
- `image_urls` → array para reference images
- `video_urls` → array para reference videos
- `audio_urls` → array para reference audios

**Límite:** max 720p. No soporta 1080p ni 2k.

### 3.3 fal.ai — Patrones anti-error

| Síntoma | Causa | Fix |
|---|---|---|
| Auth error | `Bearer` en vez de `Key` | Usar `Authorization: Key {api_key}` |
| Modelo no encontrado | app_id incorrecto | Verificar variante exacta en fal.ai dashboard |
| Timeout poll | Request en cola larga | Aumentar deadline, el queue puede ser lento |

---

## 4. Replicate

**Base URL:** `https://api.replicate.com`  
**Auth header:** `Authorization: Bearer {api_key}`

### 4.1 Prediction API

**Submit:**
```
POST https://api.replicate.com/v1/predictions
Content-Type: application/json

{
  "version": "owner/model:version-sha",
  "input": {...}
}
```

**Sync mode (rápido, <60s):**
```
Prefer: wait=60
```

**Poll:**
```
GET https://api.replicate.com/v1/predictions/{prediction_id}
```

**Estados:** `starting` → `processing` → `succeeded` | `failed` | `canceled`

**Response:**
```json
{
  "id": "...",
  "status": "succeeded",
  "output": ["https://replicate.delivery/..."],  // array de URLs
  "error": null,
  "logs": "...",
  "metrics": {"predict_time": 1.23}
}
```

**Gotcha:** `output` es siempre un array, incluso para un solo video/imagen.

**Rate limits:** 600 req/min submissions, 3000 req/min polling.

### 4.2 Replicate — Patrones anti-error

| Síntoma | Causa | Fix |
|---|---|---|
| `starting` para siempre | Cold start del worker | Esperar — puede tomar 30-90s el primer run |
| `output` es null aunque succeeded | Modelo devuelve output incremental | Hacer otro GET al terminar |
| 429 en poll | Polling demasiado agresivo | Interval mínimo 5s |

---

## 5. Patrones generales de implementación robusta

### 5.1 Retry con backoff para submits

```python
max_attempts = 8
base_delay = 8
for attempt in range(1, max_attempts + 1):
    r = requests.post(endpoint, json=payload, headers=headers, timeout=(30, 600))
    if r.ok:
        break
    if is_transient_error(r):
        time.sleep(base_delay)
        continue
    raise RuntimeError(f"API error {r.status_code}: {r.text}")
```

**Errores transitorios típicos:**
- 429 (rate limit)
- 502/503 (gateway errors)
- Asset not ready en generación

### 5.2 Extracción de ID robusta

Las APIs usan nombres inconsistentes: `id`, `Id`, `ID`, `task_id`, `taskId`, `request_id`, `prediction_id`.

```python
def extract_id(resp, *keys):
    def canon(s): return re.sub(r"[^a-z0-9]", "", str(s).lower())
    # 1. Exact match
    for k in keys:
        if k in resp:
            return resp[k]
    # 2. Canonical match
    cmap = {canon(k): v for k, v in resp.items()}
    for k in keys:
        if canon(k) in cmap:
            return cmap[canon(k)]
    # 3. Nested in resp["data"]
    nested = resp.get("data", {})
    if isinstance(nested, dict):
        for k in keys:
            if k in nested: return nested[k]
    raise RuntimeError(f"ID not found. Keys tried: {keys}. Response: {resp}")
```

### 5.3 Polling con deadline

```python
def poll_until_done(url, headers, done_states, fail_states,
                    extract_status_fn, extract_url_fn, extract_error_fn,
                    timeout=1200, interval=5, initial_wait=3):
    time.sleep(initial_wait)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        body = r.json()
        status = extract_status_fn(body).lower()
        if status in done_states:
            url = extract_url_fn(body)
            if not url:
                raise RuntimeError(f"Status done but no URL: {body}")
            return url
        if status in fail_states:
            raise RuntimeError(f"Task failed: {extract_error_fn(body)}")
        time.sleep(interval)
    raise TimeoutError(f"Timeout after {timeout}s")
```

### 5.4 Asset lifecycle completo (AnyFast)

```
1. Crear grupo (o reutilizar existing_group_id)
   POST /volc/asset/CreateAssetGroup → Id
   
2. Subir asset
   POST /volc/asset/CreateAsset (JSON para imágenes, multipart para video/audio)
   → Id (el asset_id)
   
3. Esperar Active (CRÍTICO — sin esto el asset no es usable)
   POST /volc/asset/ListAssets con GroupIds=[group_id]
   Poll cada 5s hasta Items[].Status == "Active"
   Timeout: 300s
   
4. Referenciar en generación
   "image_url": {"url": "asset://asset-id"}  (lowercase)
   role: "first_frame" | "last_frame" | "reference_image"
```

### 5.5 Diagrama de decisión: ¿asset upload o base64?

```
¿Necesitas first_frame o last_frame en AnyFast?
   SÍ → ASSET UPLOAD (asset:// obligatorio)
   NO → ¿son reference_images?
          SÍ → BASE64 inline (SeedanceRefImages → reference_images)
               más simple, no requiere upload
               (base64 también funciona via anyfast_refs)

¿Necesitas reusar la misma imagen en múltiples generaciones?
   SÍ → ASSET UPLOAD (guarda group_id y reúsalo)
   NO → BASE64 inline (más simple)
```

---

## 6. ComfyUI — Integración de nodos

### 6.1 Tipos de datos propios (no nativos de ComfyUI)

```python
# Declarar tipo propio: simplemente usar un string como nombre de tipo
RETURN_TYPES = ("SEEDANCE_API",)        # dict con api_key, provider, base_url
RETURN_TYPES = ("ANYFAST_IMAGE_REFS",)  # list of content-array dicts
RETURN_TYPES = ("SEEDANCE_IMAGE_LIST",) # list of IMAGE tensors
```

No se necesita registro especial — ComfyUI conecta puertos del mismo string.

### 6.2 Inputs opcionales vs requeridos

```python
@classmethod
def INPUT_TYPES(cls):
    return {
        "required": {"api": ("SEEDANCE_API",)},
        "optional": {
            "first_frame": ("IMAGE",),
            "existing_refs": ("ANYFAST_IMAGE_REFS", {"forceInput": True}),
            "file_path": ("STRING", {"forceInput": True}),
        }
    }
```

`forceInput: True` fuerza que el valor venga de conexión (no de widget inline).

### 6.3 Nodo OUTPUT_NODE

```python
OUTPUT_NODE = True

def my_func(self, ...):
    return {
        "ui": {"text": [str(value)]},     # mostrar en UI
        "result": (value,)                 # pasar al siguiente nodo
    }
```

### 6.4 IS_CHANGED para forzar re-ejecución

```python
@classmethod
def IS_CHANGED(cls, **kwargs):
    if kwargs.get("video") is not None:
        return float("nan")   # siempre re-ejecutar si hay input dinámico
    return kwargs.get("video_file", "")   # re-ejecutar solo si cambió el archivo
```

### 6.5 Conversión tensor IMAGE ↔ PIL ↔ base64

```python
# Tensor ComfyUI (B,H,W,C float32 0-1) → base64 data URI
def tensor_to_b64(tensor):
    np_img = (tensor[0].numpy() * 255).clip(0, 255).astype(np.uint8)
    pil = Image.fromarray(np_img).convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

# Tensor → bytes raw (para multipart upload)
def tensor_to_bytes(tensor):
    np_img = (tensor[0].numpy() * 255).clip(0, 255).astype(np.uint8)
    pil = Image.fromarray(np_img).convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue(), "image.png", "image/png"
```

### 6.6 VIDEO input de ComfyUI

```python
def video_to_path(video_input):
    source = video_input.get_stream_source()
    if isinstance(source, str):
        return source, False   # ya es path
    source.seek(0)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.write(source.read())
    tmp.close()
    return tmp.name, True      # True = caller debe borrar

# En el nodo:
try:
    path, cleanup = video_to_path(video)
    # ... usar path ...
finally:
    if cleanup and os.path.exists(path):
        os.remove(path)
```

---

## 7. Debugging — checklist

### Cuando el submit falla (4xx)

1. ✅ ¿API key correcta y del provider correcto?
2. ✅ ¿Base URL correcta? (`https://www.anyfast.ai` no `https://api.anyfast.ai`)
3. ✅ ¿Content-Type: application/json en el header?
4. ✅ ¿Todos los campos REQUERIDOS están presentes? (GroupId, AssetType, URL en CreateAsset)
5. ✅ ¿El enum es exacto? (`"2k"` no `"2K"`, `"seedance-fast"` no `"seedance_fast"`)
6. ✅ ¿El array `content` tiene al menos un item `type: text`?

### Cuando el asset falla en generación ("asset not found")

1. ✅ ¿El asset alcanzó estado `Active` en ListAssets?
2. ✅ ¿`GroupType` está en el filtro de ListAssets? Si sí → eliminarlo
3. ✅ ¿El formato del asset URI es `asset://` (lowercase) no `Asset://`?
4. ✅ ¿La URL format en el content item es exactamente `{"url": "asset://id"}`?
5. ✅ ¿El `GroupId` existe y corresponde al grupo donde se subió el asset?

### Cuando el poll nunca termina

1. ✅ ¿Estás comparando status en lowercase?
2. ✅ ¿Cubres todos los estados de éxito? (AnyFast: `success`, fal.ai: `completed`, Replicate: `succeeded`)
3. ✅ ¿El BFS walker llega al campo correcto? Agregar print del body completo en primer poll.
4. ✅ ¿El timeout es suficiente? Video generation = 1200s. Asset polling = 300s.

### Cuando el error no tiene mensaje útil

Revisar en este orden:
- **AnyFast generation:** `body.data.fail_reason`
- **AnyFast generic:** `body.error.message`
- **fal.ai:** status response `error` + `error_type` cuando `COMPLETED` con fallo
- **Replicate:** `body.error`

---

## 8. Tabla comparativa de providers

| Aspecto | AnyFast | fal.ai | Replicate |
|---|---|---|---|
| Auth header | `Bearer {key}` | `Key {key}` | `Bearer {key}` |
| Submit URL | `POST /v1/video/generations` | `POST queue.fal.run/{app_id}` | `POST /v1/predictions` |
| Poll URL | `GET /v1/video/generations/{id}` | `GET queue.fal.run/fal-ai/queue/requests/{id}/status` | `GET /v1/predictions/{id}` |
| Task ID field | `id` (respuesta submit) | `request_id` | `id` |
| Status values | `QUEUING/PROCESSING/SUCCESS/FAILED` | `IN_QUEUE/IN_PROGRESS/COMPLETED` | `starting/processing/succeeded/failed/canceled` |
| Video URL path | `body.data.data.content.video_url` | `body.video.url` (model-specific) | `body.output[0]` |
| Error field | `body.data.fail_reason` | `body.error` (en COMPLETED) | `body.error` |
| Asset management | Sí — CreateAssetGroup + CreateAsset | No | No (usa URLs externas) |
| Max resolution | 2k (Ultra) | 720p | Depende del modelo |
| Cold start | No aplica (infra dedicada) | Sí — primera run puede tardar 30-90s | Sí — `starting` puede durar minutos |

---

## 9. Gotchas no obvios — lista maestra

1. **AnyFast: `GroupType` en ListAssets** — Si se incluye `GroupType: "AIGC"` y los grupos fueron creados sin tipo → `Items: []` siempre. Omitir siempre.

2. **AnyFast: casing de `asset://`** — El endpoint de generación espera lowercase `asset://`. `Asset://` puede ser rechazado.

3. **AnyFast: `AssetType` en multipart** — Sin este campo el tipo default es `"Image"`. Video y Audio quedan mal registrados silenciosamente.

4. **AnyFast: `fail_reason` vs `error`** — El mensaje de error real en tasks fallidos está en `body.data.fail_reason`, no en `body.error.message`.

5. **fal.ai: `Key` no `Bearer`** — El header de auth usa la palabra `Key`, no `Bearer` como el resto de APIs.

6. **fal.ai: status UPPERCASE con underscore** — `IN_QUEUE`, `IN_PROGRESS`, `COMPLETED`. Diferente al patrón de Replicate y AnyFast.

7. **Replicate: cold start** — Estado `starting` puede durar 1-3 minutos en modelos poco usados. No es un error — esperar.

8. **Replicate: `output` siempre es array** — Incluso si hay un solo resultado, viene como `["https://..."]`.

9. **ComfyUI: `anyfast_refs` anula todo** — Si está conectado, ignora silenciosamente `first_frame`, `last_frame`, `reference_images`. Siempre dejar desconectado si no se usa.

10. **ComfyUI: `forceInput: True`** — Sin esto, un campo STRING puede ser un widget editable en lugar de puerto de conexión. Añadir cuando el valor siempre debe venir de otro nodo.

11. **Timeout (connect, read) tuple** — Payloads con imágenes base64 pueden ser >1 MB. Un timeout plano de 30s puede cortar el upload. Usar `(30, 600)`.

12. **AnyFast 2.0 Ultra: `"2k"` lowercase** — El API enum es `"2k"`. Enviar `"2K"` resulta en error de validación.

13. **Audio sin imagen/video** — AnyFast rechaza audio-only. Siempre acompañar con al menos una imagen o video.

14. **@image tags auto-append** — El nodo Seedance2 añade `@image1`…`@imageN` automáticamente. Escribirlos explícitamente en el prompt da mejor control de posición pero no son requeridos manualmente.

---

## 10. Estructura de este proyecto (referencia rápida)

```
nodes.py
├── _tensor_to_b64()          Tensor → data URI
├── _find_ci()                Lookup case-insensitive en dict
├── _walk_dicts()             BFS walker para extracción robusta
├── _extract_poll_fields()    Extrae status/url/progress de cualquier respuesta
├── _poll_v2()                Poll loop para Seedance 2.0
├── _first_frame()            Extrae primer frame de video (cv2)
├── _is_anyfast_asset_not_ready_error()  Detecta "asset not found" errors
├── _submit_and_poll()        Submit + poll + first_frame para AnyFast
├── _fal_generate()           Submit + poll para fal.ai
├── _extract_id()             Extracción robusta de ID con canonical matching
├── _ensure_group()           Crea o reutiliza un asset group
├── _upload_asset()           Sube imagen/video/audio a AnyFast assets
├── _wait_for_asset_active()  Poll ListAssets hasta Status=Active
├── SeedanceApiKey            Nodo: configura provider + key
├── Seedance2 / Fast / Ultra  Nodos: generación (hereda _V2Base)
├── SeedanceUploadAsset       Nodo: sube asset + espera Active
├── SeedanceAssetRef          Nodo: envuelve asset_id en ANYFAST_IMAGE_REFS
├── SeedanceAnyfastImageUpload Nodo: convierte imágenes a base64 refs
├── SeedanceReferenceVideo    Nodo: sube video como asset
├── SeedanceReferenceAudio    Nodo: sube audio como asset
├── SeedanceRefImages         Nodo: colecta hasta 9 imágenes en SEEDANCE_IMAGE_LIST
├── SeedanceExtend            Nodo: extiende video por task_id
└── SeedanceSaveVideo         Nodo: descarga y guarda el mp4
```

**Flujo de datos de tipos:**
```
SEEDANCE_API → todos los nodos que hacen llamadas HTTP
IMAGE tensors → tensor_to_b64() → data URI → content array
ANYFAST_IMAGE_REFS = list[{type, image_url, role}] → anyfast_refs port → _V2Base.generate()
SEEDANCE_IMAGE_LIST = list[IMAGE tensors] → reference_images port → _V2Base.generate()
STRING (asset://) → SeedanceAssetRef → ANYFAST_IMAGE_REFS
```
