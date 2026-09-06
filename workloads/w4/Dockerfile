# W4: multi-stage build with a heavy cacheable dependency layer and a churn layer.
# Claims tested: Blacksmith B3 (Docker build speed), WarpBuild W1c.
FROM node:22-bookworm AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --no-package-lock --no-audit --no-fund

FROM deps AS build
WORKDIR /app
# churn.txt changes every run, so this layer and everything after it rebuild.
COPY churn.txt ./
RUN node -e "const fs=require('fs');\
const n=Number(process.env.N||2500);\
fs.mkdirSync('gen',{recursive:true});\
for(let i=0;i<n;i++){fs.writeFileSync('gen/m'+i+'.ts','export const v'+i+': number = '+i+';\n');}" \
 && ./node_modules/.bin/tsc --noEmit --skipLibCheck gen/*.ts \
 && ./node_modules/.bin/esbuild gen/m0.ts --bundle --outfile=/dev/null

FROM node:22-bookworm-slim
COPY --from=build /app/churn.txt /churn.txt
CMD ["cat", "/churn.txt"]
