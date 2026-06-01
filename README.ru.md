[English](README.md) | [Русский](README.ru.md)

# Filexa2ComfyUI Connector

Подключает ComfyUI к локальной генерации Filexa, чтобы пользователи Telegram могли запускать T2I,
I2I, T2V и I2V задачи на этом ПК через сохраненные ComfyUI workflow.

Бот: https://t.me/FilexaAIBot

Не является частью ComfyUI, не аффилирован с ComfyUI и не одобрен проектом ComfyUI.

## Состав

- `__init__.py` и `filexa2comfyui.py` - backend custom node и worker Filexa.
- `web/` - панель в браузерном интерфейсе ComfyUI.
- `API_CONTRACT.md` - контракт bot-side API для совместимых серверов.
- `README.md` - английская инструкция.
- `README.ru.md` - эта инструкция.
- `LICENSE` - лицензия исходного кода.
- `NOTICE.md` - юридические уведомления и дисклеймеры.
- `SECURITY.md` - политика сообщения об уязвимостях.
- `requirements.txt` - подсказка зависимостей для ComfyUI managers.

Готовые бинарные сборки в этом репозитории не распространяются.

## Установка

1. Установи ComfyUI из официального проекта:
   https://github.com/comfyanonymous/ComfyUI
2. Запусти ComfyUI один раз и проверь, что нужный image и/или video workflow работает вручную.
3. Установи коннектор одним из способов:

   Рекомендуемый способ через интерфейс ComfyUI, если установлен ComfyUI-Manager:

   - открой `Manager` -> `Custom Nodes Manager` или `Install via Git URL`;
   - установи из `https://github.com/Teutonick/Filexa2ComfyUI`;
   - перезапусти ComfyUI после установки.

   Ручная установка через Git:

   ```powershell
   cd ComfyUI\custom_nodes
   git clone https://github.com/Teutonick/Filexa2ComfyUI
   ```

   Ручное копирование из этого репозитория Filexa тоже подходит для разработки:

   `external_soft/comfyui` -> `ComfyUI/custom_nodes/Filexa2ComfyUI`

4. Если в окружении ComfyUI нет `requests`, установи:
   `pip install -r ComfyUI/custom_nodes/Filexa2ComfyUI/requirements.txt`
5. Перезапусти ComfyUI.
6. Открой web UI ComfyUI и нажми кнопку `Filexa` в правом нижнем углу.
7. Вставь Filexa API URL и токен из Telegram-бота, затем нажми `Connect / Save`.
8. Открой image workflow и нажми `Capture Current Workflow` в блоке `Image Workflow`.
9. Открой video workflow и нажми `Capture Current Workflow` в блоке `Video Workflow`, если нужна
   локальная T2V/I2V генерация.
10. Оставь ComfyUI запущенным.

Конфигурация и snapshots хранятся здесь:

`ComfyUI/custom_nodes/Filexa2ComfyUI/data/`

После сохранения токен скрывается. Запиши его, если планируешь переиспользовать; иначе создай
новый токен в боте Filexa.

## Снапшоты

Filexa2ComfyUI использует два сохраненных API workflow:

- `data/image_snapshot.json`
- `data/video_snapshot.json`

Каждый snapshot содержит:

- полный ComfyUI API workflow;
- optional UI workflow metadata для PNG info;
- дату сохранения;
- количество нод;
- найденную привязку prompt;
- найденную привязку image input;
- короткую подсказку модели/workflow для подписи Filexa.

Prompt определяется по текстовым input в `CLIPTextEncode`, prompt, text или conditioning нодах.

Reference определяется по `LoadImage` или совместимым image-input нодам. Если image-input не найден,
snapshot считается текстовым.

Capture можно нажимать повторно: новый snapshot заменяет старый для выбранного типа.

## Выполнение задач

Image задачи используют Image Workflow snapshot:

- `image` -> T2I, prompt подставляется в найденную prompt node;
- `image_edit` -> I2I, prompt подставляется, первый reference от Filexa загружается в ComfyUI и
  ставится в найденный image input.

Video задачи используют Video Workflow snapshot:

- `video` без reference -> T2V;
- `video` с одним reference -> I2V, prompt подставляется, reference ставится в найденный image input.

Сам workflow отвечает за выбор модели, sampler settings, video nodes, размеры, формат результата и
save nodes. После изменения workflow нужно нажать Capture Current Workflow еще раз.

## Результаты

Плагин читает ComfyUI `/history/{prompt_id}`, находит первый сгенерированный media item, скачивает
его через `/view` и отправляет в Filexa.

Поддерживаемые direct result типы:

- изображения: PNG, JPEG, WebP;
- видео: MP4, WebM, MOV.

Для изображений перенесены fallback-механизмы Filexa2Wan2GP:

- короткий direct raw upload до 40 MiB;
- optional JPEG conversion before upload;
- binary chunks по 50 KiB для сжатых результатов до 3 MiB;
- JSON/base64 chunks по 8 KiB, затем безопасный режим по 4 KiB;
- local-only completion, если результат все еще слишком большой или upload невозможен.

Видео отправляется только direct upload и ограничено 50 MiB. Если видео слишком большое или upload
падает, файл остается в output папке ComfyUI, а Filexa получает нейтральный local-only completion.

## Расширенные overrides

Обычному боту Filexa они не нужны. Совместимый сервер может передавать optional fields в
`task.params`:

- `comfyui_workflow`: полный API workflow override для одной задачи;
- `prompt_binding`: `{ "node_id": "6", "input": "text" }`;
- `image_binding`: `{ "node_id": "10", "input": "image" }`;
- `reference_bindings`: map `"node_id.input"` или `"node_id.inputs.input"` в `"first"`, `"all"`,
  index или список indexes.

Без explicit reference bindings плагин использует найденный image-input binding и первый Filexa
reference.

## Диагностика

### Панель не появилась.

Проверь, что папка лежит ровно здесь:

`ComfyUI/custom_nodes/Filexa2ComfyUI`

Затем перезапусти ComfyUI и посмотри terminal на import errors.

### Capture пишет, что prompt node не найдена.

Убедись, что workflow имеет API-visible текстовый prompt input, обычно `CLIPTextEncode.text`.

### I2I или I2V пишет, что image input не найден.

Добавь `LoadImage` или совместимую image-input ноду, подключи ее в workflow и пересними snapshot.

### Результат не возвращается в Filexa.

Открой панель Filexa2ComfyUI и проверь Status/Diagnostics. При нестабильной сети плагин переключит
image upload на chunk fallback. Слишком большие изображения/видео останутся в output папке ComfyUI,
а Filexa получит local-only completion.

### Все зависло.

Отмени задачу в Filexa через `/cancel`, нажми `Cancel active task` в панели, затем перезапусти
ComfyUI, если очередь все еще заблокирована.

## Юридическое уведомление

В этом репозитории находится только исходный код Filexa2ComfyUI Connector.

Коннектор распространяется по MIT License. Бот/API Filexa предоставляются на отдельных условиях
Filexa Terms of Use и Privacy Policy:
https://teutonick.github.io/bot-legal-docs/privacy

Пользователь самостоятельно отвечает за установку ComfyUI, установку custom nodes, выбор и
лицензирование моделей, безопасность токенов, работу своего компьютера, проверку результатов и
соблюдение законов и условий третьих сторон.

Коннектор делает outbound HTTP/HTTPS requests к настроенному Filexa API endpoint и обращается к
настроенному локальному ComfyUI API URL. Он не требует открывать ComfyUI port в публичный интернет.

Security issues нужно сообщать privately по `SECURITY.md`.
