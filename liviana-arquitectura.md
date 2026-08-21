# Liviana — Arquitectura para kettenki.com

## Objetivo
Chatbot de escaparate: responde sobre KettenKI (Bambera, Liviana, Fandango, servicios, contacto) a los visitantes de kettenki.com. Sirve como demo en vivo para clientes que se plantean un chatbot como Liviana para su propio negocio.

## Stack (100% AWS, serverless, coste mínimo en reposo)

| Pieza | Servicio | Por qué |
|---|---|---|
| Frontend | Widget JS vanilla (ya integrado en el sitio) | Coherente con el resto del sitio, sin build system |
| API | API Gateway **HTTP API** (no REST API) | Más barata, suficiente para este caso de uso |
| Orquestación | Lambda (Python) | Pay-per-request, cero coste en reposo |
| LLM | Amazon Bedrock, Claude Haiku | Chat conversacional corto, coste mínimo. Si con el uso real se queda corto, es un cambio de una línea (`modelId`) pasar a Sonnet u otro modelo de Bedrock — no afecta al resto de la arquitectura |
| Memoria de conversación | DynamoDB con TTL | Barato, sin servidores, borrado automático |
| Guardarraíles | Bedrock Guardrails (opcional, valorar más adelante) | Evita que se desvíe de tema o prometa cosas que no debe |

No se propone Bedrock Knowledge Base / RAG para la v1: el contenido sobre KettenKI (qué es Bambera, Liviana, Fandango, servicios) es pequeño y cabe entero como texto en el system prompt, no hace falta búsqueda semántica. Lo que sí se guarda en **S3 como un JSON** (en vez de hardcodeado en el código de la Lambda), para poder actualizar el contenido sin redesplegar: la Lambda lo lee al arrancar (o lo cachea) y lo inyecta tal cual dentro del system prompt.

## Memoria de conversación (sliding window)

No se reenvía el historial completo en cada llamada. Enfoque:

1. Cada conversación tiene un `sessionId` (UUID generado en el frontend, guardado en `localStorage` mientras dura la sesión del navegador).
2. En DynamoDB, tabla `liviana-conversations`, partition key `sessionId`, un item con una lista de los últimos mensajes.
3. En cada turno: se leen los últimos **3-4 pares** (usuario + asistente) guardados, se anteponen al nuevo mensaje del usuario, se manda todo a Bedrock.
4. Tras la respuesta, se actualiza el item en DynamoDB añadiendo el nuevo par y recortando por el final si se supera la ventana (FIFO).
5. **TTL activado** en la tabla (p. ej. 24-48h): la conversación se borra sola, no hay que gestionar limpieza ni acumular coste de almacenamiento.

Esto es deliberadamente más simple que un resumen progresivo (summarization) del historial: para un chatbot de marketing con conversaciones cortas, la ventana deslizante de 3-4 mensajes es suficiente contexto y evita la complejidad (y el coste extra de tokens) de generar y mantener un resumen. Si en producción se viera que los usuarios alargan mucho la conversación y pierden contexto, sería el siguiente paso a añadir — no antes.

## Protecciones anti-abuso (100% gratis, sin WAF)

Se descarta AWS WAF por su coste mensual fijo (aprox. $5-10/mes base más por regla, cargo desde el minuto uno). Para el volumen de tráfico esperado (demo, no producto con miles de usuarios), estas capas gratuitas cubren el riesgo real:

1. **Lambda reserved concurrency**: límite duro de ejecuciones simultáneas (p. ej. 5-10). Gratis. Es la red de seguridad más importante: por muy fuerte que sea un ataque, nunca se dispara un número descontrolado de invocaciones a Bedrock a la vez.
2. **Throttling nativo de API Gateway**: límite de rate/burst a nivel de API. Gratis, viene incluido.
3. **Rate limiting por sesión en DynamoDB**: contador por `sessionId` (o IP si no hay sesión) con TTL de 1 minuto. Límite: **20 mensajes/minuto**. Si se supera, no se llama a Bedrock, se responde con un mensaje tipo "espera un momento".
4. **Circuit breaker de coste diario**: contador global en DynamoDB de invocaciones a Bedrock por día, con TTL/reset cada 24h. Límite: **500 invocaciones/día**. Si se alcanza, la Lambda deja de llamar a Bedrock y devuelve un mensaje genérico. Complementado con una **AWS Budget alarm** que avisa por email/SMS si el gasto mensual se dispara.
5. **Límite de `max_tokens`** en la llamada a Bedrock, tanto de entrada (recortar mensaje del usuario si es absurdamente largo) como de salida.
6. **Bedrock Guardrails** (opcional, valorar más adelante): bloqueo de temas fuera de lugar, sin compromisos de precio o contractuales inventados.
7. **System prompt con reglas explícitas** (ver siguiente sección).

Si en producción se detecta tráfico de bots real que estas capas no frenan del todo, AWS WAF (con su Bot Control gestionado) sería el siguiente paso — pero no es necesario para el lanzamiento.

## Reglas del system prompt

- Responde siempre en el idioma en el que escribe el visitante (DE, EN o ES). No hace falta detectar nada en el frontend: el propio modelo lee el mensaje y responde en ese idioma. Es una ventaja sobre el resto del sitio, que solo es DE/EN.
- Nunca inventa precios ni plazos concretos; para eso, deriva a contacto.
- Respuestas cortas, pensadas para un widget de chat, no para un documento largo.
- En el momento adecuado, invita a contactar si el visitante muestra interés real ("¿quieres esto para tu negocio? hablemos").
- No es Bambera ni Fandango: solo habla de sí misma como demo y del resto del porfolio a nivel comercial, no técnico interno.
- Temperatura baja en la llamada al modelo: respuestas más predecibles y consistentes, importante al representar la marca en una demo pública.

## Flujo de una petición

```
Usuario escribe en el widget
   → Frontend envía { sessionId, mensaje } a API Gateway (HTTP API)
   → Lambda:
       1. Lee últimos 3-4 pares de DynamoDB (si existen)
       2. Construye el prompt: system prompt + historial recortado + mensaje nuevo
       3. Llama a Bedrock (Converse API)
       4. Guarda el nuevo par en DynamoDB (con TTL)
       5. Devuelve la respuesta
   → Frontend la muestra en el widget
```

## Decisiones cerradas

Todos los puntos abiertos de este documento están decididos: modelo (Haiku), fuente de datos (JSON en S3), seguridad (capas gratuitas con umbrales de 20 msj/min por sesión y 500 invocaciones/día), e idioma (resuelto por el modelo). Listo para pasar a Claude Code.
