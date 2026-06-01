[English](README.md) | [Русский](README.ru.md)

# Filexa2ComfyUI Connector

Filexa2ComfyUI работает в связке с Telegram-ботом @FilexaAIBot, который выступает интерфейсом
управления локальными ComfyUI workflow для T2I, I2I, T2V и I2V. Цель плагина - дать пользователям
Telegram возможность генерировать изображения и видео через Filexa, используя локальные ресурсы,
модели и workflow своего компьютера.

Бот: https://t.me/FilexaAIBot

Не является частью ComfyUI, не аффилирован с ComfyUI и не одобрен проектом ComfyUI.

## Состав

- `__init__.py` и `filexa2comfyui.py` - backend custom node и worker Filexa.
- `web/` - панель в браузерном интерфейсе ComfyUI.
- `API_CONTRACT.md` - контракт bot-side API для совместимых серверов.
- `README.md` - английская инструкция.
- `README.ru.md` - эта инструкция.
- `CHANGELOG.md` - история релизов.
- `LICENSE` - лицензия исходного кода.
- `NOTICE.md` - юридические уведомления и дисклеймеры.
- `SECURITY.md` - политика сообщения об уязвимостях.
- `pyproject.toml` - метаданные для Comfy Registry.
- `.comfyignore` - файлы, которые не попадут в архив Comfy Registry.
- `.github/workflows/publish_action.yml` - optional workflow для публикации в Comfy Registry.
- `plugin_info.json` - легкие метаданные для GitHub update-check этого коннектора.
- `requirements.txt` - подсказка зависимостей для ComfyUI managers.

Готовые бинарные сборки в этом репозитории не распространяются.

## Установка

1. Установи ComfyUI из официального проекта:
   https://github.com/comfyanonymous/ComfyUI
2. Запусти ComfyUI один раз и проверь, что нужный image и/или video workflow работает вручную.
3. Установи коннектор одним из способов:

   Рекомендуемый способ после публикации в Registry, через ComfyUI-Manager:

   - открой `Manager` -> `Custom Nodes Manager`;
   - найди `Filexa2ComfyUI` или `filexa2comfyui`;
   - установи node и перезапусти ComfyUI.

   Comfy CLI после публикации в Registry:

   ```powershell
   comfy node install filexa2comfyui
   ```

   Установка по Git URL через интерфейс ComfyUI, если установлен ComfyUI-Manager:

   - открой `Manager` -> `Custom Nodes Manager` или `Install via Git URL`;
   - установи из `https://github.com/Teutonick/Filexa2ComfyUI`;
   - перезапусти ComfyUI после установки.

   Ручная установка через Git:

   ```powershell
   cd ComfyUI\custom_nodes
   git clone https://github.com/Teutonick/Filexa2ComfyUI ComfyUI-Filexa2ComfyUI
   ```

   Ручное копирование из этого репозитория Filexa тоже подходит для разработки:

   `external_soft/comfyui` -> `ComfyUI/custom_nodes/ComfyUI-Filexa2ComfyUI`

4. Если в окружении ComfyUI нет объявленных зависимостей, установи:
   `pip install -r ComfyUI/custom_nodes/ComfyUI-Filexa2ComfyUI/requirements.txt`
5. Перезапусти ComfyUI.
6. Открой web UI ComfyUI и нажми плавающую кнопку `Filexa`. Если она мешает рабочей области,
   перетащи ее за ручку `::`.
7. Вставь Filexa API URL и токен из Telegram-бота, затем нажми `Connect / Save`.
8. Сохрани именно те workflow, которые нужны: `Text to Image (T2I)`, `Image to Image (I2I)`,
   `Text to Video (T2V)` и/или `Image to Video (I2V)`.
   После загрузки каждого workflow нажимай соответствующую кнопку `Capture Current Workflow`.
9. Оставь ComfyUI запущенным.

Конфигурация и snapshots хранятся здесь:

`ComfyUI/custom_nodes/ComfyUI-Filexa2ComfyUI/data/`

После сохранения токен скрывается. Запиши его, если планируешь переиспользовать; иначе создай
новый токен в боте Filexa.

Панель показывает live-статус коннектора, готовность маршрутов, диагностику и маленькое превью
reference-изображения от Filexa, пока активна I2I/I2V задача.

При старте панель проверяет публичный GitHub `plugin_info.json`. Если доступна версия новее,
рядом с версией появятся маркер обновления и кнопка `Update`. Встроенный updater работает для
Git-установок: он запускает `git pull --ff-only` в папке custom node; после скачивания обновления
перезапусти ComfyUI. Он не запускает `pip install` и не устанавливает пакеты во время работы.

## Метаданные Comfy Registry

Registry node id: `filexa2comfyui`, а отображаемое имя: `Filexa2ComfyUI`. Для ручной Git-установки
папка по-прежнему может называться `ComfyUI-Filexa2ComfyUI`.

Перед публикацией проверь, что `PublisherId` в `pyproject.toml` совпадает с publisher id,
созданным в Comfy Registry. Сейчас указано `teutonick` под планируемый GitHub namespace.

Публикация выполняется из корня репозитория:

```powershell
comfy node publish
```

В комплекте есть GitHub Actions workflow, но он запускается только вручную (`workflow_dispatch`),
поэтому обычные push не пытаются публиковать node. Он использует `actions/checkout@v6`,
`actions/setup-python@v6` и прямой запуск `comfy node publish --token "$REGISTRY_ACCESS_TOKEN"`,
без старой Node 20 action-обертки для публикации. Добавь publishing API key Comfy Registry в секрет
репозитория с именем `REGISTRY_ACCESS_TOKEN`, затем запусти `Publish to Comfy Registry` на вкладке
Actions, когда будешь готов к публикации. После публикации workflow также отправляет
соответствующий раздел `CHANGELOG.md` в API changelog версии Comfy Registry, чтобы панель `Updates`
на странице Registry не была пустой. Чтобы заполнить changelog для уже опубликованной версии,
запусти этот же workflow с `publish_node = false`.

## Снапшоты

Filexa2ComfyUI использует четыре сохраненных API workflow:

- `data/t2i_snapshot.json`
- `data/i2i_snapshot.json`
- `data/t2v_snapshot.json`
- `data/i2v_snapshot.json`

Каждый snapshot содержит:

- полный ComfyUI API workflow;
- optional UI workflow metadata для PNG info;
- дату сохранения;
- количество нод;
- найденную привязку prompt;
- найденную привязку image input;
- найденные проблемы совместимости, которые показываются в панели;
- короткую подсказку модели/workflow для подписи Filexa.

Prompt определяется по prompt/text input в `CLIPTextEncode`, Qwen/prompt/text, encode и
conditioning нодах. Плагин старается не выбирать filename, path, negative prompt, model, seed и
поля save-node.

Reference определяется по `LoadImage` или совместимым image-input нодам. Если image-input не найден,
I2I/I2V snapshot помечается как неподходящий.

Capture можно нажимать повторно: новый snapshot заменяет старый для выбранного маршрута. Зеленая
точка означает, что маршрут готов, серая - workflow еще не сохранен, красная - Filexa не видит
нужный prompt/image input или именно этот маршрут последним упал при выполнении.

## Выполнение задач

Image задачи используют отдельные image snapshots:

- `image` -> T2I, prompt подставляется в найденную prompt node;
- `image_edit` -> I2I, prompt подставляется, первый reference от Filexa загружается в ComfyUI и
  ставится в найденный image input.

Video задачи используют отдельные video snapshots:

- `video` без reference -> T2V;
- `video` с одним reference -> I2V, prompt подставляется, reference ставится в найденный image input.

Сам workflow отвечает за выбор модели, sampler settings, video nodes, размеры, формат результата и
save nodes. После изменения workflow нужно нажать Capture Current Workflow еще раз. Если маршрут
возвращает старую картинку из ручного запуска ComfyUI, пересними именно этот маршрут и проверь, что
в workflow есть один понятный prompt/text input, который реально управляет генерацией. Filexa
предпочитает prompt-ноды, которые ведут к output/save/preview ветке, поэтому декоративные или
отключенные примеры prompt не должны выбираться. В очень сложных workflow может понадобиться более
простая prompt-нода или явный `params.prompt_binding` из advanced-интеграции.

## Результаты

Плагин читает ComfyUI `/history/{prompt_id}`, сразу завершает задачу при execution error ComfyUI,
находит первый сгенерированный media item, скачивает его через `/view` и отправляет в Filexa.

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

`ComfyUI/custom_nodes/ComfyUI-Filexa2ComfyUI`

Затем перезапусти ComfyUI и посмотри terminal на import errors.

### Маршрут красный или пишет, что prompt input не найден.

Убедись, что workflow имеет API-visible текстовый prompt input, который реально управляет
генерацией: обычно `CLIPTextEncode.text`, Qwen prompt input или простая text/prompt нода,
подключенная к генерации.

### I2I или I2V пишет, что image input не найден.

Добавь `LoadImage` или совместимую image-input ноду, подключи ее в workflow и пересними snapshot.

### Результат не возвращается в Filexa.

Открой панель Filexa2ComfyUI и проверь Status/Diagnostics. При нестабильной сети плагин переключит
image upload на chunk fallback. Слишком большие изображения/видео останутся в output папке ComfyUI,
а Filexa получит local-only completion.

### ComfyUI упал с ошибкой, а Filexa продолжала ждать.

Версия 0.2.0 и новее читает ошибки из history ComfyUI и отправляет в Filexa terminal failure плюс
аварийный cancel. Открой Diagnostics в панели, исправь исходную ошибку workflow и пересними
соответствующий маршрут T2I/I2I/T2V/I2V.

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
