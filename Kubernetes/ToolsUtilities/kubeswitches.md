# kubeswitches

## 1. Определения

**`kubeswitches`** — это утилита командной строки (CLI) для управления несколькими файлами `kubeconfig` и быстрого переключения между контекстами кластеров Kubernetes. Она обеспечивает организацию конфигурационных файлов для различных кластеров (например, `development`, `staging`, `production`) в отдельных подкаталогах, упрощая переключение активного `kubeconfig`.

## 2. Основные концепции

### Структура каталогов

Для функционирования `kubeswitches` требуется централизованная директория, содержащая подкаталоги для каждого контекста Kubernetes.

**Пример структуры:**

```
~/.kube/contexts/
├── dev
│   └── config
├── stage
│   └── config
└── prod
    └── config
```

Каждый подкаталог содержит файл `config` с полным kubeconfig для соответствующего кластера.

### Переменная окружения

Необходимо определить переменную окружения `KUBESWITCH_CONTEXT_DIR`, указывающую на основную директорию с контекстами.

**Добавление в ~/.bashrc или ~/.zshrc:**

```bash
export KUBESWITCH_CONTEXT_DIR="$HOME/.kube/contexts"
```

**Применение изменений:**

```bash
source ~/.bashrc  # или source ~/.zshrc
```

### Принцип работы

1. **Хранение:** Каждый кластер хранится в отдельном файле `config` в своей поддиректории
2. **Переключение:** При переключении контекста файл копируется в `~/.kube/config`
3. **Изоляция:** Конфигурации кластеров не смешиваются, что снижает риск ошибок

### Сравнение с альтернативами

| Инструмент | Подход | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **kubeswitches** | Отдельные файлы на кластер | Полная изоляция, простота | Копирование файлов |
| **kubectl config** | Единый файл с контекстами | Встроен в kubectl | Смешивание конфигураций |
| **kubectx** | Управление контекстами в одном файле | Быстрое переключение | Риск случайных изменений |

## 3. Практические сценарии

### 3.1. Установка

**macOS (Homebrew):**

```bash
# Если доступен в homebrew
brew install kubeswitches
```

**Ручная установка (Linux/macOS):**

```bash
# Загрузка бинарного файла (замените URL на актуальный)
curl -LO https://github.com/your-org/kubeswitches/releases/latest/download/kubeswitches-linux-amd64

# Установка
chmod +x kubeswitches-linux-amd64
sudo mv kubeswitches-linux-amd64 /usr/local/bin/kubeswitches
```

**Сборка из исходников:**

```bash
git clone https://github.com/your-org/kubeswitches.git
cd kubeswitches
go build -o kubeswitches ./cmd/kubeswitches
sudo mv kubeswitches /usr/local/bin/
```

### 3.2. Первоначальная настройка

**Шаг 1: Создание директории для контекстов**

```bash
mkdir -p ~/.kube/contexts
```

**Шаг 2: Настройка переменной окружения**

```bash
echo 'export KUBESWITCH_CONTEXT_DIR="$HOME/.kube/contexts"' >> ~/.bashrc
source ~/.bashrc
```

**Шаг 3: Резервное копирование существующего kubeconfig**

```bash
cp ~/.kube/config ~/.kube/config.backup
```

**Шаг 4: Создание первого контекста**

```bash
# Создание директории для dev-кластера
mkdir -p ~/.kube/contexts/dev

# Копирование текущей конфигурации
cp ~/.kube/config ~/.kube/contexts/dev/config
```

### 3.3. Основные команды

**Список доступных контекстов:**

```bash
kubeswitches list
```

**Пример вывода:**

```
Available contexts:
  - dev
  - stage
  - prod
```

**Переключение контекста:**

```bash
kubeswitches set dev
```

**Проверка текущего контекста:**

```bash
kubectl config current-context
```

**Просмотр конфигурации:**

```bash
kubectl config view
```

### 3.4. Добавление нового кластера

**Шаг 1: Получение kubeconfig нового кластера**

```bash
# Пример: получение от администратора кластера
# или экспорт из существующей конфигурации
kubectl config view --raw --minify > new-cluster-config.yaml
```

**Шаг 2: Создание контекста в kubeswitches**

```bash
mkdir -p ~/.kube/contexts/new-cluster
cp new-cluster-config.yaml ~/.kube/contexts/new-cluster/config
```

**Шаг 3: Переключение на новый контекст**

```bash
kubeswitches set new-cluster
```

### 3.5. Интеграция с оболочкой

**Bash/Zsh алиасы:**

```bash
# Добавление в ~/.bashrc или ~/.zshrc
alias ks='kubeswitches'
alias ksl='kubeswitches list'
alias kss='kubeswitches set'

# Функция для быстрого переключения
ksw() {
  kubeswitches set "$1"
  echo "Switched to: $(kubectl config current-context)"
}
```

**Использование:**

```bash
ksw dev    # Переключение на dev
ksw prod   # Переключение на prod
```

**Отображение текущего контекста в prompt:**

```bash
# Добавление в ~/.bashrc или ~/.zshrc
parse_kube_context() {
  if [ -f ~/.kube/config ]; then
    local context=$(kubectl config current-context 2>/dev/null)
    if [ -n "$context" ]; then
      echo " [$context]"
    fi
  fi
}

# Для bash
PS1='\u@\h:\w$(parse_kube_context)$ '

# Для zsh с oh-my-zsh
# Использовать плагин kubectx
```

### 3.6. Синхронизация с cloud-провайдерами

**GKE (Google Kubernetes Engine):**

```bash
# Получение credentials для кластера
gcloud container clusters get-credentials cluster-name --zone zone --project project

# Сохранение как отдельный контекст
mkdir -p ~/.kube/contexts/gke-prod
cp ~/.kube/config ~/.kube/contexts/gke-prod/config
```

**Yandex Cloud Managed Kubernetes:**

```bash
# Обновление kubeconfig
yc managed-kubernetes cluster get-credentials --name cluster-name --folder-id folder-id

# Сохранение как отдельный контекст
mkdir -p ~/.kube/contexts/yandex-prod
cp ~/.kube/config ~/.kube/contexts/yandex-prod/config
```

**Локальный кластер (kubeadm/k3s/minikube):**

```bash
# kubeconfig обычно находится в ~/.kube/config
# Для переключения между кластерами используйте контексты

# Сохранение как отдельный контекст
mkdir -p ~/.kube/contexts/local-prod
cp ~/.kube/config ~/.kube/contexts/local-prod/config
```

## 4. Дополнительная информация

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| kubectl | 1.20+ | Для работы с кластерами |
| Bash/Zsh | 4.0+ | Для скриптов интеграции |

### Безопасность

1. **Защита файлов kubeconfig:**

```bash
chmod 600 ~/.kube/contexts/*/config
chmod 700 ~/.kube/contexts
```

1. **Изоляция production-контекстов:**

Рассмотрите возможность хранения production kubeconfig на зашифрованных носителях или в менеджерах секретов.

### Ограничения

- **Не управляет контекстами внутри одного файла** — требует отдельной директории на кластер
- **Копирование файлов** — может быть медленнее чем переключение через `kubectl config use-context`
- **Отсутствие синхронизации** — изменения в облачных kubeconfig не синхронизируются автоматически

### Альтернативы

| Инструмент | Описание |
| :--- | :--- |
| **[kubectx](https://github.com/ahmetb/kubectx)** | Быстрое переключение между контекстами в одном файле |
| **kubectl config** | Встроенные команды управления контекстами |
| **[ctx](https://github.com/ahmetb/kubectx)** | Обёртка над kubectl config с автодополнением |

### Связанные документы

- **[kubectl](../Base/kubectl.md)** — основы работы с kubectl
- **[kubeconfig](../Base/kubeconfig.md)** — структура и использование kubeconfig
- **[Lens](./lens.md)** — GUI для управления несколькими кластерами

### Репозиторий и документация

> ⚠️ **Примечание:** Проект kubeswitches может быть менее известен. Проверьте актуальность репозитория перед использованием.

- [GitHub: поиск kubeswitches](https://github.com/search?q=kubeswitches)
- Альтернатива: **[kubectx](https://github.com/ahmetb/kubectx)** — более популярный инструмент
