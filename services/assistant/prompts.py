INTENT_ROUTER_PROMPT = """
You are the orchestrator for a CPG assistant that helps replace raw materials in products.

Current request context:
- component_name: {component_name}
- product_name: {product_name}
- supplier_name: {supplier_name}
- missing_fields: {missing_fields}

Classify the latest user message into exactly one intent:
- change_component: the user wants help replacing or substituting a raw material, ingredient, or product component
- side_question: the user is asking anything else, including greetings, general questions, unrelated requests, or broad help requests

Routing rules:
- Use change_component when the user mentions replacing, swapping, substituting, reformulating, or changing a raw material or component in a product.
- If some replacement details are still missing and the user sends a short follow-up that likely fills one of them, use change_component.
- Use side_question for all messages that are not clearly about replacing a component in a product.

Latest customer message:
{user_message}
""".strip()


CHANGE_COMPONENT_UPDATE_PROMPT = """
You are extracting replacement-request details for a CPG assistant.

Current request context:
- component_name: {component_name}
- product_name: {product_name}
- supplier_name: {supplier_name}
- missing_fields: {missing_fields}

Extract any replacement-request details explicitly provided in the latest user message.

Fields to extract:
- component_name: the raw material, ingredient, or component to replace
- product_name: the product where the component should be replaced
- supplier_name: the supplier of the current product or component

Rules:
- Only extract details stated or clearly implied in the latest user message.
- If the user provides only one missing detail, return only that field and leave the other as null.
- If the user mentions the supplier, extract it into supplier_name.
- If the message is just a short follow-up like a product name or component name, map it to the most likely missing field.
- If a field is not updated in the latest message, return null for that field.

Latest customer message:
{user_message}
""".strip()


SIDE_QUESTION_RESPONSE = "I am here to help with replacing components in product only"

CHANGE_COMPONENT_RESPONSE = (
    "I can help with replacing raw materials in a product."
)

FOLLOW_UP_QUESTIONS = {
    "component_name": "Which component would you like to replace?",
    "product_name": "In which product would you like to replace this component?",
    "supplier_name": "Who is the current supplier of this product or component?",
}
