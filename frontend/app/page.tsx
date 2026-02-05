import { Meteors } from "@/components/ui/meteors";
import TypingText from "@/components/ui/typing_text";

export default function HomePage() {
  return (
    <div className="flex min-h-screen items-center justify-center">
        <Meteors color="#88c0d0" tailColor="rgba(136, 192, 208, 0.5)">

            <div className="flex w-screen items-center justify-center py-8">
                <TypingText
                    text={["welcome to ukiyo"]}
                    typingSpeed={55}
                    deletingSpeed={50}
                    pauseDuration={0}
                    loop={true}
                    className="ml-4 text-2xl text-white"
                    cursorCharacter="|"
                    showCursor={true}
                />
            </div>

            <div className="flex w-screen items-center justify-center py-8">
                <TypingText
                    text={["","the all in one ai-powered building platform"]}
                    typingSpeed={55}
                    deletingSpeed={50}
                    pauseDuration={1400}
                    loop={false}
                    className="ml-4 text-2xl text-white"
                    cursorCharacter="|"
                    showCursor={true}
                />
            </div>
        </Meteors>
    </div>
  );
}