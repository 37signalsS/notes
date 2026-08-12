# Полезные ссылки и ресурсы по Docker

- **Docker Documentation**
  Основной источник знаний: установка, руководства по Dockerfile, Compose и API.
  - [https://docs.docker.com/](https://docs.docker.com/)

- **Docker Hub**
  Официальный реестр образов. Рекомендуется использовать образы с пометкой "Official Image" или "Verified Publisher".
  - [https://hub.docker.com/](https://hub.docker.com/)

- **Docker Roadmap**
  Публичный план развития Docker, где можно отслеживать новые функции и предлагать свои улучшения.
  - [https://github.com/docker/roadmap](https://github.com/docker/roadmap)

- **Docker Blog**
  Официальные анонсы, технические статьи и новости от команды Docker.
  - [https://www.docker.com/blog/](https://www.docker.com/blog/)

## Обучение и лаборатории

- **Play with Docker (PWD)**
  Бесплатная браузерная песочница, предоставляющая временный доступ к Docker-хостам и Swarm-кластерам.
  - [https://labs.play-with-docker.com/](https://labs.play-with-docker.com/)

- **Containers Labs by iximiuz**
  Интерактивные задачи и глубокие технические статьи по устройству контейнеров, сетей и рантаймов.
  - [https://labs.iximiuz.com/challenges](https://labs.iximiuz.com/challenges)

- **DCA Practice Questions**
  Практические вопросы для подготовки к экзамену Docker Certified Associate.
  - [https://github.com/bbachi/DCA-Practice-Questions](https://github.com/bbachi/DCA-Practice-Questions)

- **Killercoda**
  Современная платформа с интерактивными сценариями для изучения Docker, Kubernetes и подготовки к сертификациям.
  - [https://killercoda.com/](https://killercoda.com/)

## Инструменты управления (TUI/GUI)

- **Docker Extension for VS Code**
  Официальное расширение для управления контейнерами, образами и отладки приложений прямо из IDE.
  - [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=docker.docker)

- **Portainer**
  Популярный веб-интерфейс для управления Docker-окружениями (Single Host, Swarm, K8s).
  - [https://www.portainer.io/](https://www.portainer.io/)

- **Lazydocker**
  Удобный терминальный интерфейс (TUI) для быстрого мониторинга логов, очистки образов и управления контейнерами.
  - [https://github.com/jesseduffield/lazydocker](https://github.com/jesseduffield/lazydocker)

- Подробный обзор в базе: [Инструменты управления Docker (TUI, GUI, CLI)](./docker_tools.md)

## Безопасность и аудит

- **Trivy**
  Универсальный сканер уязвимостей (CVE), секретов и ошибок конфигурации в образах и IaC.
  - [https://github.com/aquasecurity/trivy](https://github.com/aquasecurity/trivy)

- **Docker Scout**
  Нативный инструмент Docker для анализа цепочки поставок (Supply Chain) и получения рекомендаций по обновлению базовых образов.
  - [https://www.docker.com/products/docker-scout/](https://www.docker.com/products/docker-scout/)

- Подробности в базе: [Сканирование Docker-образов на уязвимости](./Docker_security/vulnerability_scanning.md)

## Оптимизация и анализ образов

- **Dive**
  Инструмент для интерактивного анализа слоев образа. Позволяет найти "мусор" и неэффективно используемое место.
  - [https://github.com/wagoodman/dive](https://github.com/wagoodman/dive)

- **Slim.ai (Docker Slim)**
  Автоматическая минимизация образов на основе анализа используемых приложением системных вызовов.
  - [https://github.com/slimtoolkit/slim](https://github.com/slimtoolkit/slim)

- Подробности в базе: [Инструменты оптимизации и анализа Dockerfile](./Dockerfile/dockerfile_optimization_tools.md)
