from super_harness import KnowledgeRouter, ZhipuVisionProvider

router = KnowledgeRouter(vision=ZhipuVisionProvider())
vision_tool = router.tools()[0]
print(vision_tool.qualified_name, vision_tool.provider_definition().parameters)
