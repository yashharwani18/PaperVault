declare module 'citeproc' {
 const CSL: {
  Engine: new (sys: {retrieveLocale: (language: string) => string | false; retrieveItem: (id: string) => unknown}, style: string, language?: string, forceLanguage?: boolean) => {
   setOutputFormat(format: string): void;
   updateItems(ids: string[]): void;
   makeBibliography(): [unknown, string[]] | false;
  };
 };
 export default CSL;
}
