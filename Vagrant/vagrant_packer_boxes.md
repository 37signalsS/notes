# Vagrant: Packer и пайплайн box-образов

**Актуально для:** Vagrant 2.4.9, Packer 1.16.x

## Определения

**Packer** — инструмент HashiCorp для воспроизводимой сборки образов ОС. В контексте Vagrant используется как основной способ получения повторяемых `.box` файлов: описывает образ как код (HCL2), собирает ВМ у провайдера и упаковывает её в бокс. Общие концепции Packer (golden image, image pipeline, hardening) описаны в [Автоматизация сборки образов](../Linux/Virtualization/vm_images/image_automation.md).

**Box** — базовый шаблон ВМ в формате `.box` (тарбол: `metadata.json`, `Vagrantfile`, диск `box.ovf`/`*.qcow2`/`*.vmdk`). Жёстко привязан к провайдеру. Подробно разобран в [Vagrant Providers](./vagrant_providers.md).

**Post-Processor `vagrant` (Packer)** — этап Packer, который превращает собранную ВМ в валидный `.box` файл для конкретного провайдера (VirtualBox, Libvirt, VMware и т.д.). Именно он генерирует корректный `metadata.json` и тарбол.

**Post-Processor `vagrant-cloud` (Packer)** — этап Packer, загружающий получившийся `.box` прямиком в указанный box на Vagrant Cloud. Запускается строго после `vagrant` (цепочка).

**Vagrant Cloud** — публичный каталог (registry) box-образов и API для их публикации/раздачи. Публикация и приватные box требуют аутентификации (`vagrant login`, токен доступа). HashiCorp объявила о плановой [устарелости HCP Vagrant](https://developer.hashicorp.com/hcp/docs/vagrant/hcp-vagrant-eol): создание новых box на HCP запрещено с **1 октября 2026**, поддержка прекывается **2 ноября 2026**, окончание операций — **31 декабря 2026**. Классический `vagrantcloud.com` продолжает работать — для миграции используйте [storage providers](https://developer.hashicorp.com/vagrant/vagrant-cloud/hcp-vagrant/storage-providers).

**Box Tag (тег)** — идентификатор box в формате `ORGANIZATION/BOX_NAME` (например, `bento/ubuntu-24.04`). Используется в `Vagrantfile` (`config.vm.box`) и во всех командах `vagrant cloud`.

**Необслуживаемая установка (unattended install)** — установка ОС без интерактива: Debian/Ubuntu — `preseed`/`autoinstall`, RHEL-семейство — `kickstart`. В Packer параметры передаются builder'у (обычно через `http_directory` + boot_command) и используются для воспроизводимой сборки «чистого» образа. Общий пайплайн описан в [Image Automation](../Linux/Virtualization/vm_images/image_automation.md).

**Cloud-init** — механизм инициализации ВМ при первом старте (user-data: пользователи, SSH-ключи, сеть, пакеты). Используется и при сборке box, и при его первом запуске: многие канонические box (`generic/*`, Ubuntu Cloud) раздают SSH и сеть именно через cloud-init. Подробная теория — в [Cloud-Init в KVM](../Linux/Virtualization/kvm/cloud_init.md).

## Базовые концепции

### Место Packer в жизненном цикле box

`vagrant package` годится только для разовых упаковок уже настроенной ВМ. Для регулярных, воспроизводимых сборок используется Packer: **builder → provisioners → post-processor `vagrant` → пост-обработка/публикация**.

Общий пайплайн сборки образов (multi-stage, тестирование serverspec/testinfra, hardening, CI/CD, версионирование) — [Image Automation](../Linux/Virtualization/vm_images/image_automation.md). Данный файл покрывает только специфику **box-артефактов для Vagrant**: генерацию `.box`, его публикацию в Vagrant Cloud и приватную раздачу.

### Как собирается box для каждого провайдера

Каждый builder Packer даёт артефакт в формате конкретного гипервизора (VirtualBox → `box.ovf`/`vmdk`, Libvirt/KVM/QEMU → `qcow2`). Поэтому мульти-провайдерный box собирается **отдельной сборкой на каждый провайдер**:

- `virtualbox-iso` (VirtualBox) → post-processor `vagrant` c `provider = "virtualbox"`.
- `qemu` / `libvirt-iso` (KVM) → post-processor `vagrant` c `provider = "libvirt"`.

Итог — несколько `.box` файлов, которые публикуются под **одной версией** box с метаданными по провайдерам (`vagrant box add bento/ubuntu-24.04 --provider libvirt` выбирает нужный артефакт). Формат `metadata.json` для мульти-провайдерного box приведён в [Vagrant Providers](./vagrant_providers.md).

### Cloud-init и unattended-установка в боксах

Два способа получить «чистую» ОС при сборке box:

1. **Unattended-установка из ISO** (builder `*-iso`): Ubuntu — `autoinstall` (subiquity), Debian — `preseed`, RHEL/CentOS/Alma/Rocky — `kickstart`. Установщику отдаются параметры через HTTP (`http_directory`) и флаги ядра в `boot_command`. Результат — полностью воспроизводимая установка + провижининг (Ansible/shell) + упаковка в `.box`.
2. **Готовый cloud image + cloud-init** (builder `qemu`/`libvirt-iso` с `cloud_init`): быстрее, но база доверяется чужой сборке; настройки (пользователь `vagrant`, ключи, сеть) приходят в user-data. Так собраны многие box (`generic/*`, Ubuntu Cloud).

На стороне **потребителя** cloud-init влияет на тайминги: сразу после `vagrant up` SSH может быть недоступен, пока cloud-init не завершится (типичная причина `SSH timeout`). Перед перепаковкой готового box (`vagrant package`) или созданием снапшота нужно сбросить состояние cloud-init — иначе instance-id повторяется и user-data применяется некорректно:

```bash
# внутри гостевой ОС перед упаковкой/снапшотом
cloud-init clean --logs
```

Полный цикл «облачный образ → user-data → проверка статуса (`cloud-init status --wait`) → ресет» — в [Cloud-Init в KVM](../Linux/Virtualization/kvm/cloud_init.md).

### Версионирование

- Box на Vagrant Cloud использует **семантическое версионирование** (`1.0.0`, `202601.1`).
- В `Vagrantfile` версия фиксируется через `config.vm.box_version = "~> 202601.0"` и `config.vm.box_check_update`.
- При `vagrant up` Vagrant автоматически проверяет `vagrant box outdated` и предлагает обновление.

### Аутентификация в Vagrant Cloud

Логин нужен только для: приватных box, публикации, управления каталогом.

```bash
# Интерактивный логин (сохраняет токен в ~/.vagrant.d/)
vagrant login
# или с токеном
vagrant login --token ABC123
# проверка сессии (exit 0 = залогинен)
vagrant login --check
# кто я
vagrant cloud auth whoami
# выход
vagrant cloud auth logout
```

Для CI пайплайнов токен передаётся переменной окружения `VAGRANT_CLOUD_TOKEN` (например, из secrets GitLab/GitHub).

### Жизненный цикл публикации box

Вручную (или через API) публикация состоит из шагов: **create box → create version → create provider → upload .box → release**.

```bash
vagrant cloud box create my-org/ubuntu-24.04
vagrant cloud version create my-org/ubuntu-24.04 "202601.1" --description "Release notes"
vagrant cloud provider create my-org/ubuntu-24.04 virtualbox "202601.1"
vagrant cloud provider upload my-org/ubuntu-24.04 virtualbox "202601.1" builds/ubuntu-24.04-virtualbox.box
vagrant cloud publish my-org/ubuntu-24.04 "202601.1" libvirt builds/ubuntu-24.04-libvirt.box
```

Последняя команда `vagrant cloud publish` — «однокнопочная» альтернатива всей цепочке: создаёт box/версию/провайдера, загружает файл и помечает версию как released одним вызовом.

## Практические сценарии

### Сценарий 1: Сборка box через Packer и автопубликация (HCL2)

Минимальный шаблон сборки box для VirtualBox с публикацией в Vagrant Cloud через цепочку post-processors.

```hcl
# box-config.pkr.hcl
packer {
  required_plugins {
    virtualbox = {
      version = ">= 1.0.0"
      source  = "github.com/hashicorp/virtualbox"
    }
    vagrant = {
      version = ">= 1.1.1"
      source  = "github.com/hashicorp/vagrant"
    }
  }
}

variable "box_version" {
  default = "202601.1"
}

source "virtualbox-iso" "ubuntu" {
  iso_url          = "https://releases.ubuntu.com/24.04/ubuntu-24.04.2-live-server-amd64.iso"
  iso_checksum     = "sha256:<sha256-checksum>"
  ssh_username     = "vagrant"
  ssh_password     = "vagrant"
  ssh_wait_timeout = "3600s"
  shutdown_command = "echo 'vagrant' | sudo -S shutdown -P now"
  guest_os_type    = "Ubuntu_64"
  vm_name          = "ubuntu-24.04"
}

build {
  sources = ["source.virtualbox-iso.ubuntu"]

  provisioner "shell" {
    scripts = ["scripts/setup.sh", "scripts/cleanup.sh"]
  }

  post-processors {
    post-processor "vagrant" {
      provider = "virtualbox"
      output   = "builds/{{.Provider}}/{{.BuildName}}.box"
      keep_input_artifact = true
    }
    post-processor "vagrant-cloud" {
      box_tag      = "my-org/ubuntu-24.04"
      version      = var.box_version
      access_token = env("VAGRANT_CLOUD_TOKEN")
    }
  }
}
```

Запуск:

```bash
packer init box-config.pkr.hcl
packer validate box-config.pkr.hcl
export VAGRANT_CLOUD_TOKEN=secret
packer build box-config.pkr.hcl
```

Для Libvirt добавьте второй `source "qemu"` (или `libvirt-iso`) и вторую цепочку post-processors c `provider = "libvirt"`, либо запускайте сборки по каждому провайдеру отдельно с флагом `packer build -only=virtualbox-iso.ubuntu`.

### Сценарий 2: Публикация из готовой ВМ (без Packer)

Для разовой публикации текущей настроенной ВМ:

```bash
# 1. Остановить и упаковать ВМ в .box
vagrant halt
vagrant package --output ubuntu-24.04-custom.box

# 2. Зарегистрировать (однократно), создать версию, загрузить и release
vagrant login --token "$VAGRANT_CLOUD_TOKEN"
vagrant cloud publish my-org/ubuntu-24.04 "202601.1" \
  virtualbox ubuntu-24.04-custom.box --version-description "QA build"
```

### Сценарий 3: Публикация в CI/CD

```yaml
# .gitlab-ci.yml (фрагмент)
build_box:
  image: hashicorp/packer:1.16
  stage: build
  script:
    - packer init .
    - packer build -only=virtualbox-iso.ubuntu .
  artifacts:
    paths:
      - builds/
    expire_in: 1 week
  variables:
    VAGRANT_CLOUD_TOKEN: $BOX_PUBLISH_TOKEN   # Secret
```

При релизе тегом используйте номер версии из тега: `--version "${CI_COMMIT_TAG#v}"` или параметризуйте `-var box_version=`. Сборка с `-timestamp-ui` и `-force` обеспечивает воспроизводимые логи в CI:

```bash
packer build -force -timestamp-ui -var "box_version=${CI_COMMIT_TAG#v}" box-config.pkr.hcl
```

### Сценарий 4: Приватный box для внутренней команды

Приватная раздача требует логин у потребителя и флаг приватности при публикации.

```bash
# Публикация с флагом --private
vagrant cloud publish my-team/build-env "1.2.0" libvirt build-env.box --private

# Потребление
vagrant login
vagrant init my-team/build-env
vagrant up --provider=libvirt
```

Без логина Vagrant выдаст ошибку авторизации при загрузке приватного box (для публичных box логин не требуется).

### Сценарий 5: Air-gapped раздача без Vagrant Cloud

Для изолированных сред не обязательно использовать Vagrant Cloud: box раздаётся через внутренний HTTP(S)-сервер. Соберите `.box`, положите в хранилище (Nginx, Artifactory) и пропишите прямую ссылку + контрольную сумму:

```ruby
config.vm.box = "custom-build"
config.vm.box_url = "https://artifacts.example.com/vagrant/build-env-1.2.0.box"
# Вычисляйте checksum отдельно в CI, а не в Vagrantfile — Ruby не поддерживает $(...) в строках
config.vm.box_download_checksum = "sha256:" + `sha256sum build-env-1.2.0.box | cut -d' ' -f1`.strip
config.vm.box_download_checksum_type = "sha256"
```

### Сценарий 6: Сборка box с unattended-установкой (autoinstall)

Фрагмент сборки Ubuntu Server 24.04 для qemu/libvirt с ответами установщику через `http_directory`:

```hcl
source "qemu" "ubuntu" {
  iso_url          = "https://releases.ubuntu.com/24.04/ubuntu-24.04.2-live-server-amd64.iso"
  iso_checksum     = "sha256:<...>"
  # http_directory отдаёт autoinstall-user-data и meta-data по http://PackerIP:PackerPort/
  http_directory   = "http"
  boot_command     = [
    "<wait><enter><f6><esc><wait>",
    " autoinstall ds=nocloud-net\\;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/ ",
    "<enter>"
  ]
  ssh_username     = "vagrant"
  ssh_password     = "vagrant"
  ssh_timeout      = "30m"
  disk_size        = "20G"
  memory           = 2048
  cpus             = 2
}

build {
  sources = ["source.qemu.ubuntu"]

  provisioner "shell" {
    scripts = ["scripts/harden.sh", "scripts/cleanup.sh"]
  }

  post-processor "vagrant" {
    provider = "libvirt"
    output   = "builds/{{.Provider}}/ubuntu-24.04.box"
  }
}
```

В `http/autoinstall-user-data` задаются: разметка диска, locale/keyboard, пользователь `vagrant` (пароль только для первичного SSH), импорт SSH-ключей, `packages`, swap. Для Debian параметр ответов — `preseed`, для RHEL-семейства — `kickstart` (свои boot_command и content). Полные рецепты и тестирование box (smoke-test, testinfra/serverspec) — в [Image Automation](../Linux/Virtualization/vm_images/image_automation.md).

Отличие от варианта «готовый cloud image»: сборка из ISO полностью воспроизводима, база не доверяется третьей стороне, а результат сразу упаковывается в `.box`.

### Сценарий 7: Приватный box-реестр без Vagrant Cloud

Когда публиковать в Vagrant Cloud нельзя (изоляция, корпоративный стандарт), box раздаётся собственным хранилищем. `box_url` может указывать как на сам `.box`, так и на **директорию с `metadata.json`** (версии, провайдеры).

**Вариант A: статический HTTP (Nginx).** Раскладка каталога = тег box + версия:

```bash
mkdir -p /var/www/vagrant/boxes/team-env/1.2.0/
cp build-env-1.2.0-libvirt.box /var/www/vagrant/boxes/team-env/1.2.0/
```

```nginx
# /etc/nginx/conf.d/vagrant.conf
server {
  listen 80;
  root /var/www/vagrant;
  location /boxes/ { autoindex on; }
}
```

Потребление:

```ruby
config.vm.box = "team-env"
config.vm.box_url = "http://vagrant.example.com/boxes/team-env/1.2.0/"             # каталог (metadata.json)
config.vm.box_url = "http://vagrant.example.com/boxes/team-env/1.2.0/build-env.box" # прямая ссылка на файл
config.vm.box_download_checksum = "sha256:<...>"
config.vm.box_download_checksum_type = "sha256"
```

**Вариант B: MinIO/S3.** Приватный bucket + подписанный (presigned) URL на момент `vagrant box add`:

```bash
mc cp build-env.box myminio/vagrant/boxes/team-env/1.2.0/
mc presign myminio/vagrant/boxes/team-env/1.2.0/build-env.box   # → временный подписанный URL
vagrant box add team-env "<presigned-url>"
```

**Вариант C: Artifactory/Nexus** как Generic (raw) repository: путь `<repo>/<user>/<name>/<version>/<name>.box`. Аутентификация — userinfo в URL (`https://user:pass@host/...`, только по HTTPS) либо клиентскими сертификатами (`config.vm.box_download_client_cert`).

Главные правила: **пините checksum**, **держите версии неизменными** (иммутабельность) и раздавайте **по HTTPS**. Неконтролируемый URL без checksum допускает подмену артефакта (см. supply-chain ниже).

## Дополнительная информация

### Типичные ошибки

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Failed to create upload` при `vagrant cloud publish` | Истёк/невалиден токен; HCP composite token протух | Обновите `VAGRANT_CLOUD_TOKEN`; `vagrant cloud auth whoami` |
| `Version already exists` | Повторная публикация той же версии | Увеличьте версию или удалите через `vagrant cloud version delete` |
| `checksum mismatch` при `vagrant box add` из URL | Изменился файл без обновления контрольной суммы | Перегенерируйте checksum; используйте `--insecure` только как крайнюю меру |
| Box не виден у потребителя | Версия не released / box private без логина | `vagrant cloud version release`; у потребителя выполнить `vagrant login` |
| `Box format mismatch` в `vagrant up` | Потребитель выбрал не тот провайдер | `vagrant up --provider=libvirt` (артефакт нужен для libvirt) |

### Supply-chain безопасность box-артефактов

Box — исполняемый артефакт (внутри — образ диска с ОС и, как правило, ключами). Подмена box на этапе раздачи приводит к выполнению произвольного кода в гостевой ВМ. Меры защиты, специфичные для box:

1. **Контрольная сумма.** Для любой раздачи мимо Vagrant Cloud (URL/ФС/реестр) обязателен пиннинг `box_download_checksum`. Распространяйте `sha256` отдельным каналом, а не рядом с файлом.
2. **Подпись артефакта.** `.box` — тарбол (`metadata.json` + диск). Его можно подписать Sigstore/cosign как бинарный артефакт и проверять подпись до распаковки:

```bash
# на стороне поставщика
cosign sign-blob build-env.box --output-signature build-env.box.sig --output-certificate build-env.box.crt
# на стороне потребителя — перед vagrant box add
cosign verify-blob build-env.box --signature build-env.box.sig --certificate build-env.box.crt
```

Общая теория подписи и Sigstore — в [Artifact Signing](../Security/Supply_Chain_Security/artifact_signing.md).
3. **Сканирование содержимого.** Контейнерные сканеры (Trivy/Grype) не работают напрямую с `.box`, но диск внутри сканируется как rootfs: распакуйте `.box`, пробросьте `qcow2`/`vmdk` через `guestmount`, далее `trivy rootfs <точка-монтирования>` / `grype .`. Аналог для контейнеров — [Container Image Supply Chain](../Security/Supply_Chain_Security/container_image_supply_chain.md).
4. **Доверие источнику.** Надёжные источники — `bento/*` (Chef), HashiCorp `hashicorp/*`, официальные cloud-образы Ubuntu. Сторонние box несут и контент образа, и его историю сборки — для них обязательны проверка checksum и подписи.
5. **Минимизация встроенных секретов.** Перед публикацией удалите `insecure_private_key`, историю SSH/команд, кэши менеджеров пакетов (`cloud-init clean --logs`, `history -c`, очистка логов) — см. [Vagrant Provisioning](./vagrant_provisioning.md).

### Лучшие практики

1. **Версионируйте строго семантически** и фиксируйте версию в потребляющем `Vagrantfile` (`box_version`).
2. **Пините checksum** ISO в источнике и `.box` при раздаче через URL.
3. **Собирайте в CI**, а не на рабочей машине: воспроизводимость + единый токен публикации в secrets.
4. **Изолируйте токен**: никогда не кладите `VAGRANT_CLOUD_TOKEN` в репозиторий/Vagrantfile.
5. Для повторяемых мульти-провайдерных артефактов укажите `-only=<build>` в CI, чтобы собирать каждый провайдер отдельным джобом.
6. Иммутабельность: при изменении конфигурации выпускайте новую версию, а не перезаписывайте существующую.
7. **Supply-chain:** пините checksum при раздаче не через Vagrant Cloud, подписывайте `.box` (Sigstore/cosign) и сканируйте содержимое (`guestmount` + Trivy) перед релизом.
8. **CI/CD аудит:** логируйте кто/когда опубликовал box — используйте `-var "box_version=${CI_COMMIT_TAG#v}"` в Packer и `--version-description` в `vagrant cloud publish` для трассируемости к коммиту/тегу.

> **Примечание (2026):** HashiCorp объявила о [устарелости HCP Vagrant](https://developer.hashicorp.com/hcp/docs/vagrant/hcp-vagrant-eol) — этапированное сворачивание: создание новых box запрещено с **1 октября 2026**, поддержка прекывается **2 ноября 2026**, окончание операций — **31 декабря 2026**. Vagrant CLI и исходники на GitHub остаются доступными (open-source community edition). Для миграции используйте [storage providers](https://developer.hashicorp.com/vagrant/vagrant-cloud/hcp-vagrant/storage-providers) — S3, Azure Blob, IBM Cloud.

### См. также

- [Vagrant Providers и Образы](./vagrant_providers.md) — форматы `.box`, `metadata.json`, версионирование, источники образов, `box_url`.
- [Автоматизация сборки образов](../Linux/Virtualization/vm_images/image_automation.md) — общий пайплайн Packer: multi-stage сборка, тестирование, hardening, CI/CD.
- [Cloud-Init в KVM](../Linux/Virtualization/kvm/cloud_init.md) — user-data, NoCloud, ресет состояния перед переупаковкой.