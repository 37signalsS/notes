# Полезные ссылки для веб-серверов и анализа производительности

- **Nginx Documentation**
  Основной ресурс по настройке Nginx: директивы, модули и лучшие практики.
  - [https://nginx.org/en/docs/](https://nginx.org/en/docs/)

- **Angie Documentation**
  Документация форка Nginx от российской команды: новые модули, динамическая конфигурация и расширенная статистика.
  - [https://angie.software/docs/](https://angie.software/docs/)

- **Apache HTTP Server Documentation**
  Полное руководство по Apache 2.4: модули, конфигурационные файлы и тюнинг.
  - [https://httpd.apache.org/docs/2.4/](https://httpd.apache.org/docs/2.4/)

- **Traefik Documentation**
  Руководство по современному Edge Router: интеграция с Docker, Kubernetes и автоматический HTTPS.
  - [https://doc.traefik.io/traefik/](https://doc.traefik.io/traefik/)

- **HAProxy Documentation**
  Документация по одному из самых быстрых и надежных балансировщиков нагрузки.
  - [https://docs.haproxy.org/](https://docs.haproxy.org/)
  - Подробности в базе: [HAProxy — обзор](./haproxy_overview.md)

## Безопасность и аудит конфигураций

- **Gixy / Gixy-Next**
  Статический анализатор конфигураций Nginx/Angie. Помогает найти уязвимости (SSRF, Alias Traversal и др.) до деплоя.
  - [https://github.com/yandex/gixy](https://github.com/yandex/gixy) (Оригинал)
  - [https://github.com/GixyNext/gixy-next](https://github.com/GixyNext/gixy-next) (Актуальный форк)

- **Mozilla Observatory**
  Строгий сканер безопасности, проверяющий HTTP-заголовки, настройки TLS и CSP.
  - [https://observatory.mozilla.org/](https://observatory.mozilla.org/)

- **Security Headers**
  Быстрый аудит HTTP-заголовков безопасности (HSTS, CSP, X-Frame-Options).
  - [https://securityheaders.com/](https://securityheaders.com/)

- **Qualys SSL Labs**
  Глубокий анализ конфигурации SSL/TLS вашего сервера.
  - [https://www.ssllabs.com/ssltest/](https://www.ssllabs.com/ssltest/)

## Анализ производительности и Core Web Vitals

- **Google PageSpeed Insights**
  Анализ скорости загрузки сайта и рекомендации по оптимизации от Google на основе данных Lighthouse и Chrome User Experience Report (CrUX).
  - Ссылка: [https://pagespeed.web.dev/](https://pagespeed.web.dev/)
  - Подробности в базе: [PageSpeed Insights — руководство](./Concepts/web_performance/pagespeed_insights.md)

- **WebPageTest**
  Профессиональный инструмент для глубокого анализа производительности из различных географических локаций и на реальных устройствах. Поддерживает визуализацию Waterfall и анализ HTTP/3.
  - Ссылка: [https://www.webpagetest.org/](https://www.webpagetest.org/)
  - Подробности в базе: [WebPageTest — глубокий анализ](./Concepts/web_performance/webpagetest.md)

- **Pingdom Tools**
  Комплексный тест скорости загрузки страницы с подробным отчетом по типам контента и размерам ресурсов.
  - Ссылка: [https://tools.pingdom.com/](https://tools.pingdom.com/)

- **GTmetrix**
  Инструмент для отслеживания истории производительности и визуальных отчетов.
  - [https://gtmetrix.com/](https://gtmetrix.com/)

## Нагрузочное тестирование и бенчмаркинг

- **k6 (by Grafana)**
  Современный инструмент нагрузочного тестирования как кода (Testing as Code) на базе JavaScript/Go. Оптимален для интеграции в CI/CD.
  - Ссылка: [https://k6.io/](https://k6.io/)

- **wrk**
  Высокопроизводительный HTTP-бенчмаркер, способный генерировать огромную нагрузку при минимальном потреблении ресурсов.
  - Ссылка: [https://github.com/wg/wrk](https://github.com/wg/wrk)

- **Vegeta**
  Утилита для нагрузочного тестирования с постоянным темпом запросов (constant request rate), что критично для анализа надежности систем.
  - Ссылка: [https://github.com/tsenart/vegeta](https://github.com/tsenart/vegeta)

- **Apache Benchmark (ab)**
  Классический консольный инструмент для быстрой оценки производительности веб-сервера.
  - Документация: [https://httpd.apache.org/docs/2.4/programs/ab.html](https://httpd.apache.org/docs/2.4/programs/ab.html)

- Подробный обзор в базе: [Инструменты бенчмаркинга веб-серверов](./webserver_benchmarking.md)
