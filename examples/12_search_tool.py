from super_harness import KnowledgeRouter, ZhipuWebSearchProvider

router = KnowledgeRouter(search=ZhipuWebSearchProvider())
for item in router.tools():
    print(item.qualified_name, item.provider_definition().parameters)
