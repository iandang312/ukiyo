import { Meteors } from "@/components/ui/meteors";
import TypingText from "@/components/ui/typing_text";
import { Button } from "@/components/ui/button"
import Link from "next/dist/client/link";

export default function HomePage() {
  return (
    <div className="w-full flex flex-col">
      
      <section className="relative min-h-screen flex items-center justify-center bg-gradient-to-b from-black to-gray-900 overflow-hidden">
        <Meteors color="#88c0d0" tailColor="rgba(136, 192, 208, 0.5)">
          <div className="flex flex-col items-center justify-center space-y-6">
            
            <TypingText
              text={["welcome to ukiyo"]}
              typingSpeed={55}
              deletingSpeed={50}
              pauseDuration={0}
              loop={true}
              className="text-4xl text-white"
              cursorCharacter="|"
              showCursor={true}
            />

            <TypingText
              text={["", "the all in one ai-powered building platform"]}
              typingSpeed={55}
              deletingSpeed={50}
              pauseDuration={1400}
              loop={false}
              className="text-4xl text-white"
              cursorCharacter="|"
              showCursor={true}
            />
          </div>

          <div style={{ position: "absolute", bottom: "10%", width: "100%", display: "flex", justifyContent: "center" }}>
            <Button variant="outline" className="rounded-full hover:bg-gray-300">
              <Link href="/chat">get started</Link>
            </Button>
          </div>

        </Meteors>
      </section>

      <div className="h-32 bg-gradient-to-b from-gray-900 to-white" />

      <section className="min-h-screen bg-white flex items-center justify-center">
        <div className="max-w-4xl px-6 text-center">
          <h2 className="text-4xl text-black mb-4">
            modern teams demand tools across the entire stack.
          </h2>
          <h3 className="text-lg text-gray-600">
            ukiyo combines every industry-leading LLMs and AI models into one seamless experience.
          </h3>
          <h3 className="text-lg text-gray-600">
            simply tell us your goal, and we decide the best tools and models catered to get the job done.
          </h3>
        </div>
      </section>

      <div className="h-32 bg-gradient-to-b from-white to-gray-900" />

      <section className="relative min-h-screen flex items-center justify-center bg-gradient-to-b from-white to-white-900 overflow-hidden">
        <Meteors color="#88c0d0" tailColor="rgba(136, 192, 208, 0.5)">
          <div className="flex flex-col items-center justify-center space-y-6">
              <div className="max-w-4xl px-6 text-center">
                <h2 className="text-4xl text-white mb-4">
                  ukiyo is an open-source project
                </h2>
                <p className="text-lg text-white">
                  built by ian dang
                </p>
              </div>
          </div>
        </Meteors>
      </section>

    </div>
  );
}