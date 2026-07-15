FROM python:3.12-slim
WORKDIR /instance
COPY evaluator /evaluator
COPY instances/iab_0001 /instance
CMD ["sh", "-c", "bash setup.sh && bash reproduce_pre_fix.sh && bash apply_gold_patch.sh && bash evaluate.sh"]
