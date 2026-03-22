
  ---
  Quick usage example (OpenAI-compatible SDK)

  from openai import OpenAI
  import os

  client = OpenAI(
      base_url="https://bedrock-runtime.ap-southeast-1.amazonaws.com/v1",
      api_key=os.environ["AWS_BEARER_TOKEN_BEDROCK"]
  )

  response = client.chat.completions.create(
      model=os.environ["BEDROCK_MODEL"],
      messages=[{"role": "user", "content": "Hello!"}]
  )

   # Main model (complex tasks, agents)
  BEDROCK_MODEL_MAIN=arn:aws:bedrock:ap-southeast-1:106056766526:application-inference-profile/8fo75fa52tmk

  # Intent detection model (fast, cheap)
  BEDROCK_MODEL_INTENT=arn:aws:bedrock:ap-southeast-1:106056766526:application-inference-profile/6wbz52t5c3rz

  # Shared
  AWS_BEARER_TOKEN_BEDROCK=ABSKQmVkcm9ja0FQSUtleS15bnI5LWF0LTEwNjA1Njc2NjUyNjpLUTJLeEwza09qR0FMd2NtL3N3R0loNFUzdHJXbTZWUEd5
  VTZPeUJKS2hJcU13RWJXRW5takhWOTRrRT0=
  BEDROCK_BASE_URL=https://bedrock-runtime.ap-southeast-1.amazonaws.com
  AWS_DEFAULT_REGION=ap-southeast-1