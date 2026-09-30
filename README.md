# Cancelamento automático

Ferramenta para identificar e cancelar clientes suspensos por débito há 75+
dias (Amazonet/HubSoft). Tudo roda numa tela só, `app_validacao.py`, que
tem a **simulação** (só leitura e cálculo, não muda nada) e a **execução
real** (irreversível por este programa).

Rode sempre a **simulação** primeiro pra conferir os números antes de rodar
qualquer execução real.

## 1. Preparar o computador (só na primeira vez)

1. **Instalar o Python** (se ainda não tiver): baixe em
   [python.org/downloads](https://www.python.org/downloads/), versão 3.11 ou
   mais nova. Durante a instalação, marque a caixa **"Add python.exe to PATH"**.

2. **Abrir o terminal na pasta do projeto**: no Explorer, entre na pasta
   `Cancelamento automatico`, clique com o botão direito em um espaço vazio
   e escolha **"Abrir no Terminal"** (ou "Abrir janela do PowerShell aqui").

3. **Criar o ambiente virtual** (isola as bibliotecas deste projeto do resto
   do computador):
   ```
   python -m venv venv
   ```

4. **Ativar o ambiente virtual**:
   ```
   venv\Scripts\activate
   ```
   Se der certo, o início da linha do terminal passa a mostrar `(venv)`.

5. **Instalar as bibliotecas necessárias**:
   ```
   pip install -r requirements.txt
   ```

6. **Criar o arquivo de credenciais `.env`** na raiz da pasta do projeto
   (mesmo nível de `hubsoft.py`), com o conteúdo abaixo preenchido com as
   credenciais da API do HubSoft (peça pra quem já tem acesso, ex: TI/Ana):
   ```
   HUBSOFT_BASE_URL=https://api.amazonet.hubsoft.com.br
   HUBSOFT_CLIENT_ID=...
   HUBSOFT_CLIENT_SECRET=...
   HUBSOFT_USERNAME=...
   HUBSOFT_PASSWORD=...

   HUBSOFT_MANIA_BASE_URL=...
   HUBSOFT_MANIA_CLIENT_ID=...
   HUBSOFT_MANIA_CLIENT_SECRET=...
   HUBSOFT_MANIA_USERNAME=...
   HUBSOFT_MANIA_PASSWORD=...
   ```
   As linhas `HUBSOFT_*` são da Amazonet e as `HUBSOFT_MANIA_*` são da Mania
   (cada empresa tem seu próprio HubSoft). Os IDs internos de cada HubSoft
   (tipo de atendimento, fila, motivo etc.) ficam em `empresas.py`.
   Esse arquivo é secreto: nunca envie por e-mail/WhatsApp nem suba pro Git
   (ele já está configurado pra ser ignorado pelo `.gitignore`).

## 2. Rodar no dia a dia

Toda vez que for usar, só repete estes passos (não precisa reinstalar nada):

1. Abra o terminal na pasta do projeto (igual ao passo 2 acima).
2. Ative o ambiente virtual:
   ```
   venv\Scripts\activate
   ```
3. Rode a tela:
   ```
   streamlit run app_validacao.py
   ```
4. O navegador abre sozinho em `http://localhost:8501` com a tela. Se não
   abrir automaticamente, copie esse endereço e cole no navegador. No topo do
   menu lateral, escolha a **Empresa**: **Amazonet** ou **Mania** (a tela
   inteira passa a mostrar só os dados e o HubSoft daquela empresa).
5. Para encerrar, feche a aba do navegador e depois feche (ou aperte
   `Ctrl+C`) a janela do terminal.

## 3. O que a tela mostra

- Filtros por nome, plano, cidade, estado, contrato assinado e elegibilidade
  a multa.
- Tabela com a quantidade de clientes por plano que já atingiram 75+ dias de
  suspensão por débito.
- Um seletor de plano (a lista é a mesma da tabela acima) que, ao escolher,
  já mostra e filtra só os clientes daquele plano nas tabelas abaixo.
- Botão **"Rodar automação (simulação)"**: roda cliente por cliente e mostra
  o passo a passo que seria executado (apagar faturas vencidas, gerar a
  fatura proporcional que as substitui, cobrar multa quando aplicável, abrir
  atendimento + O.S. de retirada de equipamento, desautorizar o CPE) — sem
  chamar a API de verdade. Salva um log da simulação em `saidas/`.
- Botão **"Iniciar lote REAL"** (só libera depois de marcar a caixa de
  confirmação): executa esses passos de verdade no HubSoft para os clientes
  do plano selecionado **em blocos de 5** (10 segundos entre um cliente e
  outro). Depois de cada bloco o lote para e mostra os 5 processados; você
  confere e clica **"Aprovar e rodar os próximos 5"** (ou **"Encerrar o lote
  aqui"**). Avisos na tela mostram na hora cada cliente com pendência/falha;
  no fim fica a lista de todos os processados (com CSV) e o log completo em
  `saidas/execucao_real_<empresa>_*.json`. Se 3 cancelamentos seguidos
  falharem (ex: erro de permissão), o lote para sozinho. Não clique em nada
  na página enquanto um bloco roda — isso interrompe o bloco.
  **Não pode ser desfeito** pelo programa — revise sempre a lista antes.

## 4. Agendamento automático

No menu lateral, em **Tela**, escolha **Agendamento**. Para cada empresa dá
para configurar: ligar/desligar, **horário** (de Manaus), **dias da semana**,
**quais planos** rodam, **modo** (Simulação ou REAL) e o **máximo de
clientes por execução**. Clique em **Salvar agendamento** — fica gravado em
`agendamentos.json`. A tela mostra a próxima execução e o resultado da
última (com a lista de quem precisa de atenção).

Quem executa no horário é o **agendador**. O jeito recomendado é registrar
uma tarefa no **Agendador de Tarefas do Windows** (uma vez só, no terminal
na pasta do projeto):

```
powershell -ExecutionPolicy Bypass -File .\instalar_tarefa_agendador.ps1
```

A tarefa roda `rodar_agendador.bat` a cada 5 minutos (enquanto você estiver
logada no Windows; pode estar com a tela bloqueada) e grava a saída em
`saidas\agendador.log`. Para remover:
`powershell -ExecutionPolicy Bypass -File .\instalar_tarefa_agendador.ps1 -Remover`.

Alternativa sem tarefa: deixar uma segunda janela do terminal aberta com:

```
venv\Scripts\activate
python agendador.py
```

Ele confere a configuração a cada minuto e roda cada empresa uma vez por dia,
no horário marcado (até 60 minutos depois, se estava desligado na hora
exata). No modo REAL ele cancela sozinho, sem a aprovação de 5 em 5 da tela —
comece em **Simulação** e com um limite pequeno de clientes.

## 5. Se der algum erro

- **"streamlit não é reconhecido..."**: o ambiente virtual não está ativado
  — repita o passo `venv\Scripts\activate`.
- **Erro de autenticação com o HubSoft**: confira se o arquivo `.env` está
  na pasta certa e com as credenciais corretas.
- **Erro ao baixar dados do Metabase**: confira sua conexão com a internet;
  o link da consulta pública é fixo no código (`metabase_cancelamento.py`).
